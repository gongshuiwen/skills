"""Protocol tests use a fake engine; no model prompts, Docker or SDK required."""

from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from benchmark.tools import benchflow, results, runner
from benchmark.tools.__main__ import main

SOURCE = Path(__file__).resolve().parents[2]
REAL_CHECK = runner.check
RUNTIME = dict(benchflow="0.6.3", python="3.12.3", acp="2.6.0", codex="0.166.0",
               image="test-image", image_id="sha256:fake", proxy="", provider_endpoint_sha256="fake")


class ToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = Path(temp.name)
        for name in ("tasks", "tools", "runtime"):
            shutil.copytree(SOURCE / "benchmark" / name, self.repo / "benchmark" / name,
                            ignore=shutil.ignore_patterns("__pycache__"))
        for skill in ("test-baseline-maintenance", "documentation-baseline-maintenance"):
            shutil.copytree(SOURCE / skill, self.repo / skill)
        (self.repo / "benchmark/tests").mkdir()
        shutil.copyfile(SOURCE / "benchmark/tests/test_verifiers.py", self.repo / "benchmark/tests/test_verifiers.py")
        self.config_path = self.repo / "experiment.toml"
        self.config_path.write_text((SOURCE / "benchmark/experiment.toml").read_text().replace("repeats = 5", "repeats = 1").replace("concurrency = 4", "concurrency = 1"))
        self.config = runner.load_config(self.config_path, self.repo)
        self.calls, self.outcomes = [], {}
        self.interrupt_at = None
        self.enterContext(patch.object(runner, "REPO", self.repo))
        self.enterContext(patch.object(runner, "check", lambda path: (runner.load_config(path, self.repo), RUNTIME.copy())))
        self.enterContext(patch.multiple(benchflow, preflight=lambda: RUNTIME.copy(),
                                        checked=lambda argv, **kwargs: RUNTIME["image_id"],
                                        execute=self.fake_execute, cleanup=lambda run_id: None))
        self.enterContext(redirect_stdout(io.StringIO()))

    def fake_execute(self, config_path, log_path, run_id, stop, lock_fd, engine):
        case_id = config_path.parent.parent.name
        self.calls.append(case_id)
        if case_id == self.interrupt_at:
            self.interrupt_at = None
            raise KeyboardInterrupt()
        config = json.loads(config_path.read_text())
        task = Path(config["tasks_dir"]).name
        outcome = self.outcomes.get(case_id, 1)
        native = config_path.parent / "native" / task
        native.mkdir(parents=True)
        raw = dict(task_name=task, model=config.get("model"), skill_mode=config["skill_mode"],
                   scenes=[{"roles": [{"reasoning_effort": config.get("reasoning_effort")}]}],
                   rewards={"reward": outcome if type(outcome) in (int, float) else 1},
                   timing={"agent_execution": 1.25}, error=None, verifier_error=None,
                   task_digest="sha256:" + hashlib.sha256(task.encode()).hexdigest(),
                   final_metrics=dict(total_prompt_tokens=10, total_cached_tokens=20, total_completion_tokens=3, total_cost_usd=None),
                   agent_result={"total_tokens": 33}, usage_tracking={"usage_source": "agent_native_acp"})
        if outcome == "timeout":
            raw.update(agent_timeout_info={"timeout_sec": 900}, rewards=None, error="budget expired", partial_trajectory=True)
        elif outcome == "infra":
            raw.update(error="transport closed", error_category="transport", rewards=None)
        runner.write_json(native / "result.json", raw)
        workspace = native / "verifier/workspace"
        shutil.copytree(Path(config["tasks_dir"]) / "environment/project", workspace)
        inventory = [p.relative_to(workspace).as_posix() for p in workspace.rglob("*") if p.is_file()]
        runner.write_json(workspace / "_file_inventory.json", inventory)
        trajectory = native / "trajectory"
        trajectory.mkdir()
        events = []
        if config["skill_mode"] == "with-skill" and outcome != "unread":
            skill = self.config["tasks"][task]
            events = [dict(type="tool_call", status="completed", title=f"cat /skills/{skill}/SKILL.md")]
        (trajectory / "acp_trajectory.jsonl").write_text("".join(json.dumps(event) + "\n" for event in events))
        return 0, False

    def frozen(self):
        root = runner.freeze(self.config, RUNTIME, self.config_path, self.repo)
        return root, json.loads((root / "manifest.json").read_text())

    def completed(self):
        self.assertEqual(runner.run(self.config_path), 0)
        root = next((self.repo / "benchmark/.runtime").iterdir())
        return root, json.loads((root / "manifest.json").read_text())

    def test_plan_derives_counts_and_balances_pairs(self):
        config = dict(self.config, repeats=5)
        cases = runner.plan(config)
        self.assertEqual(len(cases), 44)
        self.assertEqual(len({case["id"] for case in cases}), 44)
        self.assertEqual(cases, runner.plan(config))
        model = [case for case in cases if case["condition"] != "oracle"]
        for a, b in zip(model[::2], model[1::2]):
            self.assertEqual((a["task"], a["repeat"]), (b["task"], b["repeat"]))
            self.assertEqual({a["condition"], b["condition"]}, {"A", "B"})

    def test_bad_config_is_rejected(self):
        original = self.config_path.read_text()
        for changed in (original.replace("repeats = 1", "repeats = true"),
                        original.replace("concurrency = 1", "concurrency = 0"),
                        original.replace("test-refactoring =", '"../outside" ='),
                        "unknown = 1\n" + original):
            with self.subTest(config=changed):
                self.config_path.write_text(changed)
                with self.assertRaises(ValueError):
                    runner.load_config(self.config_path, self.repo)

    def test_check_validates_structure_without_launching_models(self):
        calls = []
        with patch.object(benchflow, "cli", side_effect=lambda argv: calls.append(argv)), patch.object(runner.subprocess, "run"):
            config, runtime = REAL_CHECK(self.config_path, self.repo)
        self.assertEqual(config["repeats"], 1)
        self.assertEqual(runtime, RUNTIME)
        self.assertEqual(len(calls), 4)
        self.assertFalse(self.calls)

    def test_working_changes_are_frozen_and_lf_is_used(self):
        path = self.repo / "benchmark/tasks/test-refactoring/verifier/check.py"
        path.write_bytes(path.read_bytes() + b"\r\n# uncommitted\r\n")
        root, manifest = self.frozen()
        captured = (root / "snapshot/tasks/test-refactoring/verifier/check.py").read_bytes()
        self.assertIn(b"# uncommitted\n", captured)
        self.assertNotIn(b"\r\n", captured)
        runner.validate_snapshot(root, manifest)

    def test_zero_score_and_timeout_are_terminal_on_resume(self):
        cases = runner.plan(self.config)
        model = [case for case in cases if case["condition"] != "oracle"]
        self.outcomes[model[0]["id"]] = 0
        self.outcomes[model[1]["id"]] = "timeout"
        root, manifest = self.completed()
        first_calls = self.calls.copy()
        data = results.report(root)
        self.assertTrue(data["complete"])
        self.assertEqual(data["evaluated"], 8)
        self.assertEqual(data["statuses"]["agent_timeout"], 1)
        self.assertEqual(runner.run(resume=root), 0)
        self.assertEqual(self.calls, first_calls)

    def test_oracle_failure_blocks_all_models_even_on_resume(self):
        self.outcomes[runner.plan(self.config)[0]["id"]] = 0
        self.assertEqual(runner.run(self.config_path), 1)
        root = next((self.repo / "benchmark/.runtime").iterdir())
        self.assertTrue(all(name.endswith("-oracle") for name in self.calls))
        previous = self.calls.copy()
        self.assertEqual(runner.run(resume=root, retry_infra=True), 1)
        self.assertEqual(self.calls, previous)

    def test_interruption_resumes_without_repeating_scored_zero(self):
        model = [case for case in runner.plan(self.config) if case["condition"] != "oracle"]
        self.outcomes[model[0]["id"]] = 0
        self.interrupt_at = model[1]["id"]
        with self.assertRaises(KeyboardInterrupt):
            runner.run(self.config_path)
        root = next((self.repo / "benchmark/.runtime").iterdir())
        self.assertFalse(results.report(root)["complete"])
        self.assertEqual(runner.run(resume=root), 0)
        self.assertEqual(self.calls.count(model[0]["id"]), 1)
        self.assertEqual(self.calls.count(model[1]["id"]), 2)
        self.assertTrue((root / "jobs" / model[1]["id"] / "attempt-001/attempt.json").is_file())
        self.assertTrue((root / "jobs" / model[1]["id"] / "attempt-002/attempt.json").is_file())

    def test_infra_retry_requires_explicit_flag_and_keeps_history(self):
        case = next(case for case in runner.plan(self.config) if case["condition"] == "A")
        self.outcomes[case["id"]] = "infra"
        self.assertEqual(runner.run(self.config_path), 1)
        root = next((self.repo / "benchmark/.runtime").iterdir())
        count = len(self.calls)
        self.assertEqual(runner.run(resume=root), 1)
        self.assertEqual(len(self.calls), count)
        self.outcomes[case["id"]] = 1
        self.assertEqual(runner.run(resume=root, retry_infra=True), 0)
        row = next(row for row in results.report(root)["results"] if row["case_id"] == case["id"])
        self.assertEqual(len(row["attempts"]), 2)
        self.assertEqual(row["attempts"][0]["status"], "infra_error")

    def test_resume_rejects_changed_snapshot_before_execution(self):
        root, _ = self.completed()
        target = root / "snapshot/tasks/test-refactoring/environment/project/pricing.py"
        target.write_text(target.read_text() + "\n# tampered\n")
        before = len(self.calls)
        with self.assertRaisesRegex(ValueError, "Frozen input"):
            runner.run(resume=root)
        self.assertEqual(len(self.calls), before)
        self.assertFalse(results.report(root)["complete"])

    def test_resume_uses_frozen_config_and_inputs(self):
        root, _ = self.completed()
        before = self.calls.copy()
        self.config_path.write_text(self.config_path.read_text().replace("repeats = 1", "repeats = 8"))
        (self.repo / "benchmark/tasks/test-refactoring/environment/project/pricing.py").write_text("changed\n")
        self.assertEqual(runner.run(resume=root), 0)
        self.assertEqual(self.calls, before)

    def test_unread_available_skill_is_retained_and_missing_metrics_are_null(self):
        case = next(case for case in runner.plan(self.config) if case["condition"] == "B")
        self.outcomes[case["id"]] = "unread"
        root, _ = self.completed()
        data = results.report(root)
        row = next(row for row in data["results"] if row["case_id"] == case["id"])
        self.assertFalse(row["skill_read"])
        native = root / row["result_path"]
        raw = json.loads(native.read_text())
        raw.pop("final_metrics")
        raw.pop("agent_result")
        runner.write_json(native, raw)
        data = results.report(root)
        row = next(row for row in data["results"] if row["case_id"] == case["id"])
        self.assertTrue(data["complete"])
        self.assertIsNone(row["cost_usd"])
        self.assertIsNone(row["total_tokens"])

    def test_offline_report_rebuilds_outputs_without_backend(self):
        root, _ = self.completed()
        for name in ("summary.json", "summary.csv", "report.md"):
            (root / name).unlink()
        with patch.object(benchflow, "preflight", side_effect=AssertionError("must stay offline")):
            self.assertEqual(main(["report", "--run", str(root)]), 0)
        self.assertTrue((root / "diffs").is_dir())
        self.assertEqual(len(list((root / "diffs").glob("*.patch"))), 8)

    def test_concurrent_report_regeneration_keeps_complete_json(self):
        root, _ = self.completed()
        with ThreadPoolExecutor(max_workers=2) as pool:
            reports = list(pool.map(lambda _: results.report(root), range(2)))
        self.assertTrue(all(report["complete"] for report in reports))
        self.assertTrue(json.loads((root / "summary.json").read_text())["complete"])

    def test_duplicate_result_cannot_replace_a_failure(self):
        root, manifest = self.completed()
        case = next(case for case in manifest["cases"] if case["condition"] == "A")
        first = root / "jobs" / case["id"] / "attempt-001"
        raw_path = next((first / "native").rglob("result.json"))
        raw = json.loads(raw_path.read_text())
        raw["rewards"] = {"reward": 0}
        runner.write_json(raw_path, raw)
        second = first.with_name("attempt-002")
        shutil.copytree(first, second)
        data = results.report(root)
        self.assertFalse(data["complete"])
        self.assertTrue(any("terminal" in issue for issue in data["integrity_issues"]))
        before = self.calls.copy()
        self.assertEqual(runner.run(resume=root, retry_infra=True), 1)
        self.assertEqual(self.calls, before)

    def test_cancelled_partial_native_result_stays_resumable(self):
        root, manifest = self.completed()
        case = next(case for case in manifest["cases"] if case["condition"] == "A")
        row = results.case_result(root, manifest, case)
        raw_path = root / row["result_path"]
        raw = json.loads(raw_path.read_text())
        raw.update(rewards=None, error="cancelled", model=None, scenes=[], partial_trajectory=True)
        runner.write_json(raw_path, raw)
        metadata = root / row["attempt"] / "attempt.json"
        meta = json.loads(metadata.read_text())
        meta["state"] = "interrupted"
        runner.write_json(metadata, meta)
        self.assertEqual(results.case_result(root, manifest, case)["status"], "interrupted")
        self.assertEqual(runner.run(resume=root), 0)
        self.assertEqual(len(results.case_result(root, manifest, case)["attempts"]), 2)

    def test_unclassified_error_is_not_retried_as_infrastructure(self):
        root, manifest = self.completed()
        case = next(case for case in manifest["cases"] if case["condition"] == "A")
        row = results.case_result(root, manifest, case)
        raw_path = root / row["result_path"]
        raw = json.loads(raw_path.read_text())
        raw.update(error="unclassified failure", error_category="other", rewards=None)
        runner.write_json(raw_path, raw)
        self.assertEqual(results.case_result(root, manifest, case)["status"], "invalid")
        before = self.calls.copy()
        self.assertEqual(runner.run(resume=root, retry_infra=True), 1)
        self.assertEqual(before, self.calls)

    def test_skill_content_read_with_wildcard_is_observed(self):
        path = self.repo / "trajectory.jsonl"
        path.write_text(json.dumps(dict(type="tool_call", status="completed", title="cat /skills/*/SKILL.md",
                                       content=[{"type": "text", "text": "unique complete skill text"}])) + "\n")
        seen, evidence = results.skill_evidence(path, "test-skill", "unique complete skill text")
        self.assertTrue(seen)
        self.assertEqual(evidence[0]["kind"], "content")
        self.assertEqual(results.skill_evidence(path.with_name("missing"), "test-skill", "text"), (None, []))


class ProcessAndGuardTests(unittest.TestCase):
    def test_agent_user_guard_checks_content_and_absence(self):
        with tempfile.TemporaryDirectory() as tmp:
            agent_home = Path(tmp)
            skill = agent_home / ".agents/skills/test-skill/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("expected")
            env = dict(BENCHMARK_SKILL_NAMES='["test-skill"]', BENCHMARK_EXPECT_SKILL="test-skill",
                       BENCHMARK_SKILL_SHA256=hashlib.sha256(b"expected").hexdigest())
            with patch.dict(os.environ, env), patch.object(Path, "home", return_value=agent_home), redirect_stderr(io.StringIO()):
                exec(benchflow.SKILL_GUARD, {})
                skill.write_text("wrong")
                with self.assertRaises(SystemExit) as caught:
                    exec(benchflow.SKILL_GUARD, {})
                self.assertEqual(caught.exception.code, 86)
                os.environ["BENCHMARK_EXPECT_SKILL"] = ""
                with self.assertRaises(SystemExit):
                    exec(benchflow.SKILL_GUARD, {})

    @unittest.skipUnless(sys.platform == "linux", "Linux/WSL process and file-lock semantics")
    def test_child_holds_lease_and_cancellation_releases_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / "engine.py"
            marker = root / "started"
            engine.write_text("from pathlib import Path\nimport time\nPath(" + repr(str(marker)) + ").touch()\ntime.sleep(60)\n")
            stop, outcome, errors = threading.Event(), [], []
            def execute(fd):
                try:
                    outcome.append(benchflow.execute(root / "config.json", root / "log", "unit-test", stop, fd, engine))
                except Exception as exc:
                    errors.append(exc)
            with runner.locked(root) as fd:
                thread = threading.Thread(target=execute, args=(fd,))
                thread.start()
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
            try:
                with self.assertRaisesRegex(RuntimeError, "already owned"):
                    with runner.locked(root):
                        pass
            finally:
                stop.set()
                thread.join(timeout=20)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            self.assertTrue(outcome[0][1])
            with runner.locked(root):
                pass

    def test_cleanup_only_removes_labeled_resources(self):
        calls = []
        def checked(command, **kwargs):
            calls.append(command)
            return "owned-id" if "--filter" in command else ""
        with patch.object(benchflow, "checked", checked):
            benchflow.cleanup("specific-run")
        listings = [call for call in calls if "--filter" in call]
        self.assertEqual(len(listings), 2)
        self.assertTrue(all("label=skills.benchmark.run=specific-run" in call for call in listings))
        removals = [call for call in calls if "rm" in call]
        self.assertTrue(all(call[-1] == "owned-id" for call in removals))


if __name__ == "__main__":
    unittest.main()
