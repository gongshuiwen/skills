# Skills baseline benchmark

Four native BenchFlow tasks compare the two repository skills against the same
agent without the tested skill. The small Python CLI manages frozen inputs,
oracle calibration, repeated A/B execution, resume and offline reports.

## Environment

Run from the repository root with **Linux/WSL, Python 3.12+, Docker Engine and
Docker Compose**. Authenticate Codex in the Linux user's home, or supply
OPENAI_API_KEY through the environment. Credentials are not experiment settings.

Install the pinned engine in a virtual environment:

    python3 -m venv benchmark/.runtime/venv
    . benchmark/.runtime/venv/bin/activate
    python -m pip install -r benchmark/requirements.txt

Build the shared agent image once:

    docker build --tag skills-benchmark-agent:codex-acp-2.6.0-codex-0.166.0 \
      --file benchmark/runtime/Dockerfile benchmark/runtime

The recipe pins the Python base digest, Node 22.20.0, Codex ACP 2.6.0 and
Codex 0.166.0. A small compatibility shim supports BenchFlow 0.6.3 and checks the
installed packages before prompting. Changes to these versions require
revalidation. The recipe uses BuildKit's npm cache mount for repeated builds.

Optional local environment variables:

| Variable | Purpose |
| --- | --- |
| BENCHMARK_AGENT_IMAGE | Use an existing image containing the pinned agent packages; its image ID is frozen |
| BENCHMARK_PROXY | HTTP(S) proxy reachable from containers, without URL credentials |
| HTTP_PROXY / HTTPS_PROXY | Host-side network configuration; pass Docker build proxy arguments when needed |

Docker build supports its standard HTTP_PROXY, HTTPS_PROXY, http_proxy and
https_proxy build arguments. The runtime proxy is local configuration; it is
not a value to copy from another machine.

## Commands

    python -m benchmark.tools check --config benchmark/experiment.toml
    python -m benchmark.tools run --config benchmark/experiment.toml

The committed TOML config selects model, reasoning effort, repeats, concurrency,
execution-order seed, and the task-to-skill mapping. The default plan has four
oracle cases and 40 model samples: four tasks x two conditions x five repeats.

- **check** validates the configuration, dependencies, image versions, Docker,
  native task structure and scorer regression tests. It sends no model prompts.
- **run** checks the environment, creates a unique run directory, freezes the
  current working-tree inputs, runs all oracles, then starts the A/B samples.
  All oracles must score 1 before any model sample starts.
- **report** rebuilds JSON, CSV, Markdown and workspace diffs from saved files.
  It needs no Docker, BenchFlow installation, credentials or model requests.

The seed controls task ordering, not model generation. A/B are adjacent in the
plan and alternate their starting order across repeats. Concurrency controls how
many independent cases run at once.

## Resume and interruption

The runner prints its absolute run directory. Resume that directory:

    python -m benchmark.tools run --resume <run-directory>

Resume reads the frozen config, checks snapshot hashes and runtime versions,
and skips both scored passes and scored failures. Budget timeouts also remain
terminal failures. It does not reload the original TOML or current task files.

Infrastructure failures are retained and are retried only when explicitly
requested:

    python -m benchmark.tools run --resume <run-directory> --retry-infra

Every retry creates a new attempt directory. Invalid or duplicate native results
require inspection and are not automatically retried. Oracle task failures
remain terminal; a changed solution or scorer belongs in a new experiment.

Ctrl-C stops further submission, interrupts active child process groups and
cleans only containers/networks labeled for this run. Partial reports and
attempts are retained. A filesystem lease prevents simultaneous runners; children
inherit the lease, so a surviving child after a hard kill prevents duplicate
submission until it exits. Resume recovers a completed native result even when
the parent did not finalize the attempt metadata.

A run exits 0 when every planned model sample has a terminal task outcome and
oracle/integrity checks pass. Scored zeroes and budget timeouts are completed
outcomes; infrastructure errors or missing samples give exit 1. Configuration
and environment errors give exit 2; Ctrl-C gives exit 130.

## Artifacts and isolation

Everything generated stays under the Git-ignored benchmark/.runtime directory:

    <run-id>/
      manifest.json
      snapshot/
      jobs/<case-id>/attempt-001/
        attempt.json
        config.json
        run.log
        native/
      diffs/
      summary.json
      summary.csv
      report.md

The immutable manifest records the plan, model, skill mapping, snapshot hashes,
Git commit and actual runtime/image versions. Snapshots include uncommitted
working-tree changes. UTF-8 code, Markdown, configuration and shell text use LF
in the snapshot. Per-attempt JSON and native engine outputs retain all attempts;
summaries are derived and can be regenerated.

Before the agent starts, a guard runs as the actual sandbox user: A must not
read any configured benchmark skill, and B must be able to read exactly its
designated skill with the expected content hash. Normal agent initialization is
used. Agents receive the project fixture; BenchFlow owns the oracle and verifier
surfaces. Common observation hooks capture the final non-hidden workspace after
scoring and label Docker resources for cancellation.

Availability and observed use are separate. A readable but unobserved skill
stays in B; a missing trajectory is reported as unknown. A completed read command
or returned skill content supplies auditable read evidence, including wildcard
reads. Such evidence does not establish compliance with every instruction.

Keep raw logs and local configuration private. Reports contain selected metrics
and relative artifact paths, and do not copy the authentication file.

## Tasks and scoring

| Task | Skill | Primary check |
| --- | --- | --- |
| test-refactoring | test-baseline-maintenance | Shared calculation, preserved public behavior and original regression detection |
| test-duplicate-cleanup | test-baseline-maintenance | Consolidate redundant tests; detect three state-guard mutations |
| docs-config-change | documentation-baseline-maintenance | Correct config keys/defaults, current examples and canonical links |
| docs-duplicate-cleanup | documentation-baseline-maintenance | Consolidate guides; retain unique instructions, navigation and historical ADR |

Scoring revision 2 replaces the test-refactoring method-count cap with a
nonempty, passing suite that detects all four regression categories represented
by the original tests. Both public APIs must reach the same internal helper.
Independent behavior checks include rounding, discounts, invalid lines and
iterables. Test-method counts are not a pass/fail proxy for redundancy. The
deduplication task retains its separate cleanup bound and state-guard mutations.

The configuration-docs scorer permits retired variable names in explicit
deprecation/migration explanations. Old executable examples need a clear
historical or negative label. Current deployment examples must use the correct
keys and defaults; unrelated warnings do not excuse stale instructions.

Binary scores remain a small-fixture signal. Reports show planned/evaluated
counts, failures, time means and medians, token components and skill-read
evidence. Missing metrics and costs stay null, not zero. Time includes
provider/tool/platform waiting. Equal scores and repeated all-pass outcomes do
not establish equivalence or generalize to diverse maintenance projects.

Offline report regeneration:

    python -m benchmark.tools report --run <run-directory>

Offline rescoring and additional diagnostic probes are later increments.
The first version retains the workspace and scoring versions needed for them.

## Tests

    python3 -B -m unittest discover -s benchmark/tests -v

Scorer tests exercise positive and negative examples. Protocol tests use fake
native results and subprocesses to cover oracle gating, zero-score/timeout
retention, interruption, explicit infrastructure retries, snapshot integrity,
exclusive leases, skill guards and offline reports. They send no model prompts
and need no Docker or BenchFlow installation. The suite uses Linux/WSL for the
shell-based oracle fixtures and process/lease tests.
