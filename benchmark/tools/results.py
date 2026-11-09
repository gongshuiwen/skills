"""Offline result normalization and reproducible JSON/CSV/Markdown reports."""

from collections import Counter
import csv
from datetime import datetime
import difflib
import hashlib
import io
import json
import math
from pathlib import Path
import re
import statistics
import tempfile

INFRA_CATEGORIES = {"install_failure", "pipe_closed", "acp_error", "infra_failure", "sandbox_setup",
                    "provider_auth", "provider_rate_limit", "api_error", "suspected_api_error", "transport"}


def write_text(path, content, encoding="utf-8"):
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        temporary = Path(directory) / "content"
        temporary.write_text(content, encoding=encoding, newline="")
        temporary.replace(path)


def hashes(directory):
    return {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def snapshot_issues(root, manifest):
    expected, actual = manifest["snapshot_sha256"], hashes(root / "snapshot")
    return [f"Frozen input changed: {name}" for name in sorted(expected.keys() | actual.keys())
            if expected.get(name) != actual.get(name)]


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def skill_evidence(trajectory, skill, content):
    if not trajectory.is_file():
        return None, []
    evidence = []
    for line in trajectory.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "tool_call" or event.get("status") != "completed":
            continue
        title = event.get("title") or ""
        output = "\n".join(_strings([event.get("content"), event.get("raw_output")])).replace("\r\n", "\n")
        full_content = bool(content.strip()) and content.strip() in output
        named_reader = (skill + "/SKILL.md" in title and
                        re.search(r"\b(cat|head|tail|sed|Get-Content|type)\b|read_text|Read file", title, re.I))
        if full_content or named_reader:
            evidence.append(dict(title=title, kind="content" if full_content else "completed_read_command"))
    return bool(evidence), evidence


def _attempt_result(root, manifest, case, attempt):
    row = dict(case_id=case["id"], task=case["task"], condition=case["condition"], repeat=case["repeat"],
               attempt=attempt.relative_to(root).as_posix(), status="pending", score=None,
               raw_score=None, error=None, error_category=None, result_path=None, task_digest=None,
               duration_seconds=None, agent_seconds=None, input_tokens=None, cached_tokens=None,
               output_tokens=None, total_tokens=None, cost_usd=None, usage_source=None,
               skill_read=None, skill_read_evidence=[], tool_calls=None)
    try:
        meta = json.loads((attempt / "attempt.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return dict(row, status="invalid", error=f"Unreadable attempt metadata: {exc}")
    if meta.get("case_id") != case["id"]:
        return dict(row, status="invalid", error="Attempt identity differs from manifest")
    found, malformed = [], False
    for path in sorted((attempt / "native").rglob("result.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            malformed = True
            continue
        if isinstance(data, dict) and data.get("task_name") == case["task"]:
            found.append((path, data))
    if len(found) > 1:
        return dict(row, status="invalid", error="Multiple native results for one attempt")
    if not found:
        state = meta.get("state")
        status = "interrupted" if state == "interrupted" else "running" if state == "running" else "infra_error"
        if malformed and state not in ("running", "interrupted"):
            status = "invalid"
        return dict(row, status=status, error=meta.get("error") or ("Native result missing" if status != "running" else None))
    path, data = found[0]
    row["result_path"] = path.relative_to(root).as_posix()
    metrics, native = data.get("final_metrics") or {}, data.get("agent_result") or {}
    row.update(task_digest=data.get("task_digest"), error_category=data.get("error_category"),
               raw_score=number((data.get("rewards") or {}).get("reward")),
               agent_seconds=number((data.get("timing") or {}).get("agent_execution")),
               input_tokens=number(metrics.get("total_prompt_tokens")), cached_tokens=number(metrics.get("total_cached_tokens")),
               output_tokens=number(metrics.get("total_completion_tokens")), total_tokens=number(native.get("total_tokens")),
               cost_usd=number(metrics.get("total_cost_usd")), usage_source=(data.get("usage_tracking") or {}).get("usage_source"),
               tool_calls=number(data.get("n_tool_calls")))
    try:
        row["duration_seconds"] = (datetime.fromisoformat(data["finished_at"]) - datetime.fromisoformat(data["started_at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        pass
    normal_terminal = (row["raw_score"] in (0, 1) and not data.get("error")
                       and not data.get("verifier_error") and not data.get("partial_trajectory"))
    if (meta.get("state") == "interrupted" and not normal_terminal
            and not data.get("agent_timeout_info") and not data.get("idle_timeout_info")):
        return dict(row, status="interrupted", error="Execution interrupted by runner")
    if case["condition"] != "oracle":
        skill = manifest["config"]["tasks"][case["task"]]
        content = (root / "snapshot/skills" / skill / skill / "SKILL.md").read_text(encoding="utf-8")
        row["skill_read"], row["skill_read_evidence"] = skill_evidence(path.parent / "trajectory/acp_trajectory.jsonl", skill, content)
        roles = (data.get("scenes") or [{}])[0].get("roles") or [{}]
        expected_mode = "with-skill" if case["condition"] == "B" else "no-skill"
        if (data.get("model") != manifest["config"]["model"] or data.get("skill_mode") != expected_mode
                or roles[0].get("reasoning_effort") != manifest["config"]["reasoning_effort"]):
            return dict(row, status="invalid", error="Native model, effort or skill condition differs from plan")
    if data.get("agent_timeout_info") or data.get("idle_timeout_info"):
        return dict(row, status="agent_timeout", score=0, error=data.get("error"))
    if data.get("verifier_error"):
        return dict(row, status="infra_error", error=data["verifier_error"])
    if data.get("error"):
        return dict(row, status="infra_error" if data.get("error_category") in INFRA_CATEGORIES else "invalid",
                    error=data["error"])
    if data.get("partial_trajectory"):
        return dict(row, status="interrupted", error="Partial native trajectory")
    if row["raw_score"] not in (0, 1):
        return dict(row, status="invalid", error="Expected a binary native reward")
    return dict(row, status="scored", score=row["raw_score"])


def case_result(root, manifest, case):
    directory = root / "jobs" / case["id"]
    attempts = [_attempt_result(root, manifest, case, path) for path in sorted(directory.glob("attempt-*")) if path.is_dir()]
    if not attempts:
        return dict(case_id=case["id"], task=case["task"], condition=case["condition"],
                    repeat=case["repeat"], status="pending", score=None, error=None, attempts=[])
    terminal = [row for row in attempts if row["status"] in ("scored", "agent_timeout")]
    row = dict(attempts[-1])
    if terminal and terminal[0]["attempt"] != attempts[-1]["attempt"]:
        row.update(status="invalid", score=None, error="An attempt was made after a terminal task outcome")
    row["attempts"] = attempts
    return row


def workspace_diff(root, row):
    after = (root / row["result_path"]).parent / "verifier/workspace"
    inventory = after / "_file_inventory.json"
    if not inventory.is_file():
        return {"warning": "Final workspace capture unavailable"}
    names = json.loads(inventory.read_text())
    if not isinstance(names, list) or any(not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts for name in names):
        return {"warning": "Invalid workspace inventory"}
    before = root / "snapshot/tasks" / row["task"] / "environment/project"
    originals = {p.relative_to(before).as_posix() for p in before.rglob("*") if p.is_file()}
    changed, lines = [], []
    for name in sorted(originals | set(names)):
        left, right = before / name, after / name
        old = left.read_bytes() if name in originals else b""
        if name in names and not right.is_file():
            return {"warning": f"Captured file missing: {name}"}
        new = right.read_bytes() if name in names else b""
        if old == new and (name in originals) == (name in names):
            continue
        changed.append(name)
        try:
            lines.extend(difflib.unified_diff(old.decode("utf-8").splitlines(keepends=True),
                                            new.decode("utf-8").splitlines(keepends=True),
                                            fromfile="before/" + name, tofile="after/" + name))
        except UnicodeDecodeError:
            lines.append(f"Binary file changed: {name}\n")
    directory = root / "diffs"
    directory.mkdir(exist_ok=True)
    patch = directory / (row["case_id"] + ".patch")
    write_text(patch, "".join(lines))
    return dict(changed_files=changed, diff=patch.relative_to(root).as_posix())


def _average(rows, key):
    values = [row[key] for row in rows if number(row.get(key)) is not None]
    return dict(n=len(values), mean=statistics.mean(values) if values else None,
                median=statistics.median(values) if values else None)


def report(root):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported experiment schema version")
    config, cases = manifest["config"], manifest["cases"]
    expected = {(task, condition, repeat) for task in config["tasks"] for condition in ("A", "B")
                for repeat in range(1, config["repeats"] + 1)}
    expected |= {(task, "oracle", 0) for task in config["tasks"]}
    identities = [(case["task"], case["condition"], case["repeat"]) for case in cases]
    if len(set(case["id"] for case in cases)) != len(cases) or len(set(identities)) != len(cases) or set(identities) != expected:
        raise ValueError("Manifest sample plan is incomplete or duplicated")
    issues, warnings = snapshot_issues(root, manifest), []
    rows = [case_result(root, manifest, case) for case in cases]
    for row in rows:
        if row["status"] == "invalid":
            issues.append(f"{row['case_id']}: {row['error']}")
        if row.get("result_path") and row["condition"] != "oracle":
            row["workspace"] = workspace_diff(root, row)
            if row["workspace"].get("warning"):
                warnings.append(f"{row['case_id']}: {row['workspace']['warning']}")
        components = [row.get(key) for key in ("input_tokens", "cached_tokens", "output_tokens")]
        if row.get("total_tokens") is not None and all(number(value) is not None for value in components):
            if row["total_tokens"] != sum(components):
                warnings.append(f"{row['case_id']}: native token components differ from total")
    for task in config["tasks"]:
        digests = {row["task_digest"] for row in rows if row["task"] == task and row.get("task_digest")}
        if len(digests) > 1:
            issues.append(f"{task}: native task digests differ")
    model = [row for row in rows if row["condition"] != "oracle"]
    oracle = [row for row in rows if row["condition"] == "oracle"]
    terminal = ("scored", "agent_timeout")
    oracle_passed = all(row["status"] == "scored" and row["score"] == 1 for row in oracle)
    groups = []
    for task in config["tasks"]:
        for condition in ("A", "B"):
            group = [row for row in model if row["task"] == task and row["condition"] == condition]
            evaluated = [row for row in group if row["status"] in terminal]
            groups.append(dict(task=task, condition=condition, planned=len(group), evaluated=len(evaluated),
                               passed=sum(row["score"] == 1 for row in evaluated),
                               statuses=dict(Counter(row["status"] for row in group)),
                               observed_skill_reads=sum(row.get("skill_read") is True for row in group),
                               unknown_skill_reads=sum(row.get("skill_read") is None for row in group),
                               agent_seconds=_average(evaluated, "agent_seconds"),
                               total_tokens=_average(evaluated, "total_tokens")))
    data = dict(schema_version=1, run_id=manifest["run_id"], planned=len(model),
                evaluated=sum(row["status"] in terminal for row in model),
                oracle_passed=oracle_passed, statuses=dict(Counter(row["status"] for row in model)),
                complete=oracle_passed and all(row["status"] in terminal for row in model) and not issues,
                integrity_issues=issues, warnings=warnings, groups=groups, results=rows)
    write_text(root / "summary.json", json.dumps(data, indent=2) + "\n")
    fields = ["case_id", "task", "condition", "repeat", "status", "score", "raw_score",
              "agent_seconds", "duration_seconds", "input_tokens", "cached_tokens", "output_tokens",
              "total_tokens", "cost_usd", "usage_source", "skill_read", "tool_calls", "error", "error_category", "result_path"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    write_text(root / "summary.csv", stream.getvalue(), "utf-8-sig")
    lines = ["# Skill benchmark", "", f"Run: {manifest['run_id']}",
             f"Model: {config['model']}; reasoning effort: {config['reasoning_effort']}",
             f"Oracle calibration passed: {oracle_passed}. Model samples evaluated: {data['evaluated']}/{len(model)}.",
             f"Complete: {data['complete']}. Status counts: {data['statuses']}.", "",
             "| Task | Condition | Passed / evaluated | Planned | Agent seconds mean / median | Mean total tokens | Skill reads observed / unknown |",
             "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
    def fmt(value):
        return f"{value:.1f}" if value is not None else "unavailable"
    for group in groups:
        seconds = group["agent_seconds"]
        lines.append(f"| {group['task']} | {group['condition']} | {group['passed']}/{group['evaluated']} | {group['planned']} | "
                     f"{fmt(seconds['mean'])} / {fmt(seconds['median'])} | {fmt(group['total_tokens']['mean'])} | "
                     f"{group['observed_skill_reads']} / {group['unknown_skill_reads']} |")
    lines += ["", "A: tested skill absent. B: designated skill provided. Available but unread B samples are retained.",
              "Budget timeouts count as task failures; infrastructure errors and missing samples are shown separately.",
              "Skill-read observations do not prove instruction compliance. A missing trajectory is unknown, not zero reads.",
              "Total tokens include uncached input, cache reads and output when supplied by the native agent.",
              "Missing metrics and costs remain unavailable. Times include provider/tool/platform waiting.",
              "Repeated runs describe these fixed tasks; equal scores or all passes do not establish equivalence.",
              "All attempts, including failures and interruptions, are preserved. Original native results are unchanged.", "",
              "Integrity issues: " + ("; ".join(issues) or "none"),
              "Artifact/metric warnings: " + ("; ".join(warnings) or "none"), ""]
    write_text(root / "report.md", "\n".join(lines))
    print(f"REPORT {root}: {data['evaluated']}/{len(model)} evaluated; complete={data['complete']}", flush=True)
    return data
