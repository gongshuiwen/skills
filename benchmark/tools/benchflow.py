"""Pinned BenchFlow/Codex integration. The rest of the runner uses only stdlib."""

import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from urllib.parse import urlparse

BENCHFLOW_VERSION = "0.6.3"
DEFAULT_IMAGE = "skills-benchmark-agent:codex-acp-2.6.0-codex-0.166.0"
VERSION_CHECK = r'''
const fs = require("fs");
const p = "/opt/benchflow/js-agents/lib/node_modules/@agentclientprotocol/codex-acp";
const paths = [p + "/node_modules/@openai/codex/package.json",
 "/opt/benchflow/js-agents/lib/node_modules/@openai/codex/package.json"];
const file = paths.find(x => fs.existsSync(x));
const acp = require(p + "/package.json").version;
const codex = file && require(file).version;
if (process.version !== "v22.20.0" || acp !== "2.6.0" || codex !== "0.166.0") process.exit(1);
const cp = require("child_process"), path = require("path");
const info = require(file), bin = typeof info.bin === "string" ? info.bin : info.bin.codex;
const nativeVersion = cp.execFileSync(process.execPath, [path.join(path.dirname(file), bin), "--version"], {encoding: "utf8"});
const adapterVersion = cp.execFileSync("/opt/benchflow/bin/codex-acp", ["--version"], {encoding: "utf8"});
if (!nativeVersion.includes("0.166.0") || !adapterVersion.includes("2.6.0")) process.exit(1);
console.log(JSON.stringify({acp, codex}));
'''
SKILL_GUARD = r'''
import hashlib, json, os, sys
from pathlib import Path
expected = os.environ.get("BENCHMARK_EXPECT_SKILL", "")
names = json.loads(os.environ["BENCHMARK_SKILL_NAMES"])
for name in names:
    paths = [Path.home()/".agents/skills"/name/"SKILL.md",
             Path.home()/".codex/skills"/name/"SKILL.md", Path("/skills")/name/"SKILL.md"]
    readable = [p for p in paths if os.access(p, os.R_OK)]
    if name == expected:
        if not readable or any(hashlib.sha256(p.read_bytes()).hexdigest() !=
                               os.environ["BENCHMARK_SKILL_SHA256"] for p in readable):
            print("BENCHMARK_SKILL_GUARD_FAILED: expected skill unavailable or changed", file=sys.stderr)
            sys.exit(86)
    elif readable:
        print("BENCHMARK_SKILL_GUARD_FAILED: unexpected tested skill", file=sys.stderr)
        sys.exit(86)
print("BENCHMARK_SKILL_GUARD_OK: " + (expected or "none"), file=sys.stderr)
'''
CAPTURE = r'''
from pathlib import Path
import json, shutil
source, target = Path("/app"), Path("/logs/verifier/workspace")
target.mkdir(parents=True, exist_ok=True)
files = []
for path in sorted(source.rglob("*")):
    relative = path.relative_to(source)
    if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
        continue
    if path.is_file() and not path.is_symlink():
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        files.append(relative.as_posix())
(target / "_file_inventory.json").write_text(json.dumps(files))
'''


def checked(argv, timeout=60):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{argv[0]} failed: {(result.stdout + result.stderr)[-3000:]}")
    return result.stdout.strip()


def preflight():
    if sys.platform != "linux" or sys.version_info < (3, 12):
        raise ValueError("Use Python 3.12+ on Linux/WSL.")
    try:
        version = importlib.metadata.version("benchflow")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("Install benchmark/requirements.txt in the active Python environment.") from exc
    if version != BENCHFLOW_VERSION:
        raise ValueError(f"Expected benchflow=={BENCHFLOW_VERSION}, found {version}.")
    checked(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=15)
    checked(["docker", "compose", "version"], timeout=15)
    image = os.environ.get("BENCHMARK_AGENT_IMAGE", DEFAULT_IMAGE)
    image_id = checked(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
    versions = json.loads(checked(["docker", "run", "--rm", image,
                                 "/opt/benchflow/node/bin/node", "-e", VERSION_CHECK]))
    # BenchFlow copies only the registered credential file into the sandbox.
    if not (Path.home() / ".codex/auth.json").is_file() and not os.environ.get("OPENAI_API_KEY"):
        raise ValueError("Codex authentication is missing: sign in or set OPENAI_API_KEY.")
    proxy = os.environ.get("BENCHMARK_PROXY", "")
    if proxy:
        parsed = urlparse(proxy)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in proxy):
            raise ValueError("BENCHMARK_PROXY must be an HTTP(S) proxy URL without credentials or whitespace.")
    endpoint = os.environ.get("OPENAI_BASE_URL", "")
    return dict(benchflow=version, python=sys.version.split()[0], image=image, image_id=image_id,
                **versions, proxy=proxy,
                provider_endpoint_sha256=hashlib.sha256(endpoint.encode()).hexdigest())


def prepare_task(task_dir, runtime):
    """Add the same observation/ownership hooks to every condition's snapshot."""
    environment = task_dir / "environment"
    if (environment / "docker-compose.yaml").exists():
        raise ValueError("First-version fixtures must use a Dockerfile without a custom compose file.")
    dockerfile = environment / "Dockerfile"
    text = dockerfile.read_text()
    if not text.startswith("FROM "):
        raise ValueError(f"Expected a simple Dockerfile: {dockerfile}")
    lines = text.splitlines()
    lines[0] = "FROM " + runtime["image"]
    if runtime["proxy"]:
        proxy = json.dumps(runtime["proxy"])
        lines.insert(1, f"ENV HTTP_PROXY={proxy} HTTPS_PROXY={proxy} http_proxy={proxy} https_proxy={proxy} NO_PROXY=localhost,127.0.0.1,::1")
    dockerfile.write_text("\n".join(lines) + "\n")
    label = {"skills.benchmark.run": "$" + "{BENCHMARK_RUN_ID}"}
    compose = {"services": {"main": {"labels": label}}, "networks": {"default": {"labels": label}}}
    (environment / "docker-compose.yaml").write_text(json.dumps(compose))
    verifier = task_dir / "verifier"
    (verifier / "test.sh").rename(verifier / "score.sh")
    wrapper = ('#!/usr/bin/env bash\nset +e\nbash /verifier/score.sh\nscore_status=$?\n'
               "python3 -B - <<'CAPTURE_WORKSPACE'\n" + CAPTURE +
               "\nCAPTURE_WORKSPACE\nexit \"$score_status\"\n")
    (verifier / "test.sh").write_text(wrapper)


def cli(args):
    checked([sys.executable, str(Path(__file__).resolve()), *args])


def execute(config_path, log_path, run_id, stop, lock_fd, engine):
    environment = os.environ.copy()
    environment.update(BENCHMARK_RUN_ID=run_id, PYTHONUTF8="1", PYTHONUNBUFFERED="1",
                       BENCHFLOW_NO_PROGRESS="1", BENCHFLOW_PROGRESS="on")
    with log_path.open("w") as output:
        process = subprocess.Popen(
            [sys.executable, str(engine), "eval", "run", "--config", str(config_path)],
            env=environment, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True, pass_fds=(lock_fd,),
        )
        while process.poll() is None:
            if stop.wait(0.25):
                for sig, timeout in ((signal.SIGINT, 10), (signal.SIGTERM, 5), (signal.SIGKILL, 5)):
                    if process.poll() is not None:
                        break
                    try:
                        os.killpg(process.pid, sig)
                        process.wait(timeout=timeout)
                    except (ProcessLookupError, subprocess.TimeoutExpired):
                        pass
                return process.wait(), True
        return process.returncode, False


def cleanup(run_id):
    """Only resources labeled by this experiment are eligible for removal."""
    for kind, listing in (("container", ["docker", "ps", "-aq"]),
                          ("network", ["docker", "network", "ls", "-q"])):
        try:
            ids = checked([*listing, "--filter", "label=skills.benchmark.run=" + run_id], timeout=15).split()
            if ids:
                command = ["docker", "rm", "-f", *ids] if kind == "container" else ["docker", "network", "rm", *ids]
                checked(command, timeout=30)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print(f"Cleanup warning for {run_id}: {exc}", file=sys.stderr)


def activate():
    """The compatibility shim is intentionally limited to the verified version."""
    if importlib.metadata.version("benchflow") != BENCHFLOW_VERSION:
        raise RuntimeError(f"Unsupported BenchFlow version; expected {BENCHFLOW_VERSION}")
    import shlex
    import benchflow.acp.runtime as acp_runtime
    from benchflow.agents.registry import AGENTS, register_agent

    original = AGENTS["codex-acp"]
    settings = {name: getattr(original, name) for name in inspect.signature(register_agent).parameters if name != "name"}
    settings.update(
        install_cmd="/opt/benchflow/node/bin/node -e " + shlex.quote(VERSION_CHECK),
        acp_model_config_id="model", acp_effort_config_id="reasoning_effort",
        disallow_web_tools_launch_suffix=" -c 'web_search=\"disabled\"'",
        launch_cmd="python3 -B -c " + shlex.quote(SKILL_GUARD) + " && exec " + original.launch_cmd,
    )
    register_agent("codex-acp", **settings)
    legacy_select = acp_runtime._select_acp_model_id

    def select_model(model, agent, session):
        if agent == "codex-acp" and acp_runtime._resolve_acp_model_option_id(AGENTS.get(agent), session):
            return acp_runtime._format_acp_model(model, agent)
        return legacy_select(model, agent, session)

    acp_runtime._select_acp_model_id = select_model


if __name__ == "__main__":
    # A standalone benchflow.py must not shadow the installed benchflow package.
    sys.path = [item for item in sys.path if Path(item).resolve() != Path(__file__).resolve().parent]
    activate()
    from benchflow.cli.main import app
    app()
