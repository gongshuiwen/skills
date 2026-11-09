"""Frozen experiment plans, oracle gating and resumable local execution."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import threading
import tomllib
import uuid

from . import benchflow, results

REPO = Path(__file__).resolve().parents[2]
FIELDS = {"model", "reasoning_effort", "repeats", "concurrency", "order_seed", "tasks"}
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    results.write_text(path, json.dumps(value, indent=2) + "\n")


def load_config(path, repo=None):
    repo = REPO if repo is None else repo
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    if set(config) - FIELDS:
        raise ValueError(f"Unknown configuration fields: {sorted(set(config) - FIELDS)}")
    for key in ("model", "reasoning_effort"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    for key in ("repeats", "concurrency", "order_seed"):
        if type(config.get(key)) is not int or (key != "order_seed" and config[key] < 1):
            raise ValueError(f"{key} must be an integer" + (" >= 1" if key != "order_seed" else ""))
    if not isinstance(config.get("tasks"), dict) or not config["tasks"]:
        raise ValueError("tasks must map task names to skill directory names")
    for task, skill in config["tasks"].items():
        if not NAME.fullmatch(task) or not isinstance(skill, str) or not NAME.fullmatch(skill):
            raise ValueError("Task and skill names must use lowercase letters, numbers and hyphens")
        task_dir, skill_dir = repo / "benchmark/tasks" / task, repo / skill
        for directory in (task_dir, skill_dir):
            if not directory.is_dir() or not directory.resolve().is_relative_to(repo.resolve()):
                raise ValueError(f"Missing or external input directory: {directory}")
        for relative in ("task.md", "environment/Dockerfile", "oracle/solve.sh", "verifier/test.sh"):
            if not (task_dir / relative).is_file():
                raise ValueError(f"Missing task input: {task_dir / relative}")
        metadata = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        if not re.search(rf"^name:\s*{re.escape(skill)}\s*$", metadata, re.M):
            raise ValueError(f"SKILL.md name must match directory: {skill}")
    return config


def plan(config):
    tasks = list(config["tasks"])
    cases = [dict(id=f"{task}-oracle", task=task, condition="oracle", repeat=0) for task in tasks]
    rng = random.Random(config["order_seed"])
    for repeat in range(1, config["repeats"] + 1):
        ordered = tasks.copy()
        rng.shuffle(ordered)
        for task in ordered:
            conditions = ["A", "B"]
            if (repeat + tasks.index(task)) % 2:
                conditions.reverse()
            for condition in conditions:
                cases.append(dict(id=f"{task}-{condition}-r{repeat:02d}", task=task,
                                  condition=condition, repeat=repeat))
    return cases


def check(config_path, repo=None):
    repo = REPO if repo is None else repo
    config = load_config(config_path, repo)
    runtime = benchflow.preflight()
    print(f"Runtime: BenchFlow {runtime['benchflow']}, Codex {runtime['codex']}, ACP {runtime['acp']}", flush=True)
    for task in config["tasks"]:
        benchflow.cli(["tasks", "check", str(repo / "benchmark/tasks" / task)])
        print(f"Task structure: {task} OK", flush=True)
    subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s",
                    str(repo / "benchmark/tests"), "-p", "test_verifiers.py", "-v"], check=True)
    count = len(config["tasks"]) * 2 * config["repeats"]
    print(f"CHECK OK: {len(config['tasks'])} oracle cases; {count} model samples; no model prompts sent.", flush=True)
    return config, runtime


def copy_inputs(source, destination):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in (".git", "__pycache__", ".runtime") for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Input symlinks are not supported: {path}")
        if not path.is_file() or path.suffix == ".pyc":
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix in (".sh", ".py", ".md", ".toml", ".json", ".yaml", ".yml", ".txt") or path.name == "Dockerfile":
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(path, target)


def freeze(config, runtime, config_path, repo=None):
    repo = REPO if repo is None else repo
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    root = repo / "benchmark/.runtime" / run_id
    root.mkdir(parents=True)
    snapshot = root / "snapshot"
    for task in config["tasks"]:
        target = snapshot / "tasks" / task
        copy_inputs(repo / "benchmark/tasks" / task, target)
        benchflow.prepare_task(target, runtime)
    for skill in sorted(set(config["tasks"].values())):
        copy_inputs(repo / skill, snapshot / "skills" / skill / skill)
    copy_inputs(repo / "benchmark/tools", snapshot / "tools")
    tests = snapshot / "tests"
    tests.mkdir()
    shutil.copyfile(repo / "benchmark/tests/test_verifiers.py", tests / "test_verifiers.py")
    copy_inputs(repo / "benchmark/runtime", snapshot / "runtime")
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    manifest = dict(schema_version=1, run_id=run_id, created_at=now(), config=config, runtime=runtime,
                    source_config=str(config_path.resolve()), git_commit=git.stdout.strip() if git.returncode == 0 else None,
                    normalization="UTF-8 code, Markdown and shell files use LF in the snapshot",
                    cases=plan(config), snapshot_sha256=results.hashes(snapshot),
                    policy=dict(automatic_retries=0, agent_timeout="failure", unread_available_skill="retain"),
                    scope="Linux/WSL, Docker, BenchFlow 0.6.3, Codex ACP 2.6.0")
    write_json(root / "manifest.json", manifest)
    return root


def validate_snapshot(root, manifest):
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported experiment schema version")
    if results.snapshot_issues(root, manifest):
        raise ValueError("Frozen input changed or is missing; start a new experiment instead of resuming")


@contextmanager
def locked(root):
    import fcntl
    with (root / ".run.lock").open("a+") as lease:
        try:
            fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This run is already owned by a runner or a surviving child process") from exc
        lease.seek(0)
        lease.truncate()
        lease.write(str(os.getpid()))
        lease.flush()
        yield lease.fileno()


def native_config(root, manifest, case, attempt):
    config = manifest["config"]
    native = dict(tasks_dir=str(root / "snapshot/tasks" / case["task"]), environment="docker",
                  jobs_dir=str(attempt / "native"), agent="oracle" if case["condition"] == "oracle" else "codex",
                  skill_mode="with-skill" if case["condition"] == "B" else "no-skill",
                  concurrency=1, max_retries=0, skip_install=False)
    if case["condition"] != "oracle":
        skill = config["tasks"][case["task"]]
        skill_dir = root / "snapshot/skills" / skill
        native.update(model=config["model"], reasoning_effort=config["reasoning_effort"],
                      agent_env=dict(BENCHMARK_SKILL_NAMES=json.dumps(sorted(set(config["tasks"].values()))),
                                     BENCHMARK_EXPECT_SKILL=skill if case["condition"] == "B" else "",
                                     BENCHMARK_SKILL_SHA256=hashlib.sha256((skill_dir / skill / "SKILL.md").read_bytes()).hexdigest()))
        if case["condition"] == "B":
            native["skills_dir"] = str(skill_dir)
    return native


def run_phase(root, manifest, cases, retry_infra, stop, lock_fd):
    def execute(case):
        if stop.is_set():
            return
        previous = results.case_result(root, manifest, case)
        if previous["status"] in ("scored", "agent_timeout", "invalid"):
            return
        if previous["status"] == "infra_error" and not retry_infra:
            return
        if previous["status"] == "running":
            old_meta = root / previous["attempt"] / "attempt.json"
            recovered = json.loads(old_meta.read_text())
            recovered.update(state="interrupted", finished_at=now(), error="Runner ended before a complete native result")
            write_json(old_meta, recovered)
        directory = root / "jobs" / case["id"]
        directory.mkdir(parents=True, exist_ok=True)
        number = len(list(directory.glob("attempt-*"))) + 1
        attempt = directory / f"attempt-{number:03d}"
        attempt.mkdir()
        meta = dict(schema_version=1, case_id=case["id"], state="running", started_at=now())
        write_json(attempt / "attempt.json", meta)
        write_json(attempt / "config.json", native_config(root, manifest, case, attempt))
        print(f"START {case['id']} attempt {number}", flush=True)
        try:
            expected = manifest["runtime"]
            actual = benchflow.checked(["docker", "image", "inspect", expected["image"], "--format", "{{.Id}}"])
            if actual != expected["image_id"]:
                raise RuntimeError("Agent image changed")
            code, interrupted = benchflow.execute(attempt / "config.json", attempt / "run.log",
                                                  manifest["run_id"], stop, lock_fd,
                                                  root / "snapshot/tools/benchflow.py")
            meta.update(state="interrupted" if interrupted else "finished", exit_code=code)
        except Exception as exc:
            meta.update(state="infra_error", error=str(exc))
        except BaseException:
            meta["state"] = "interrupted"
            raise
        finally:
            meta["finished_at"] = now()
            write_json(attempt / "attempt.json", meta)
        row = results.case_result(root, manifest, case)
        print(f"FINISH {case['id']} {row['status']} score={row['score']}", flush=True)

    pool = ThreadPoolExecutor(max_workers=manifest["config"]["concurrency"])
    try:
        futures = [pool.submit(execute, case) for case in cases]
        for future in as_completed(futures):
            future.result()
    except BaseException:
        stop.set()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def run(config_path=None, resume=None, retry_infra=False):
    if resume:
        root = resume.resolve()
    else:
        config_path = config_path or REPO / "benchmark/experiment.toml"
        config, runtime = check(config_path)
        root = freeze(config, runtime, config_path)
    manifest = json.loads((root / "manifest.json").read_text())
    print(f"RUN DIRECTORY: {root}", flush=True)
    stop = threading.Event()
    with locked(root) as lock_fd:
        validate_snapshot(root, manifest)
        if resume:
            if benchflow.preflight() != manifest["runtime"]:
                raise ValueError("Runtime differs from the frozen experiment")
            benchflow.cleanup(manifest["run_id"])
        try:
            oracles = [case for case in manifest["cases"] if case["condition"] == "oracle"]
            run_phase(root, manifest, oracles, retry_infra, stop, lock_fd)
            oracle_rows = [results.case_result(root, manifest, case) for case in oracles]
            if any(row["status"] != "scored" or row["score"] != 1 for row in oracle_rows):
                print("Oracle calibration incomplete or failed; model execution has not started.", flush=True)
                return 1
            cases = [case for case in manifest["cases"] if case["condition"] != "oracle"]
            run_phase(root, manifest, cases, retry_infra, stop, lock_fd)
        finally:
            if stop.is_set():
                benchflow.cleanup(manifest["run_id"])
            summary = results.report(root)
    return 0 if summary["complete"] else 1
