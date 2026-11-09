"""Usage: python -m benchmark.tools {check,run,report}."""

import argparse
from pathlib import Path
import sys
import subprocess

from . import results, runner


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Check configuration and runtime; no model prompts")
    check.add_argument("--config", type=Path, default=runner.REPO / "benchmark/experiment.toml")
    run = commands.add_parser("run", help="Calibrate oracles and execute a frozen A/B plan")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--config", type=Path)
    source.add_argument("--resume", type=Path)
    run.add_argument("--retry-infra", action="store_true", help="Explicitly retry infrastructure failures on resume")
    report = commands.add_parser("report", help="Rebuild summaries offline")
    report.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            runner.check(args.config)
            return 0
        if args.command == "report":
            data = results.report(args.run.resolve())
            return 0 if data["complete"] else 1
        if args.retry_infra and not args.resume:
            parser.error("--retry-infra requires --resume")
        return runner.run(args.config, args.resume, args.retry_infra)
    except KeyboardInterrupt:
        print("Interrupted; results are retained. Use run --resume to continue.", file=sys.stderr)
        return 130
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
