# Skills baseline benchmark (MVP)

This directory contains **four small, reproducible BenchFlow tasks** for the two skills in this repository. Each task has a frozen input project, an outcome-based verifier, and an independent oracle reference implementation. All task prompts are skill-neutral.

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), and a running Docker daemon.
- The [BenchFlow CLI](https://github.com/benchflow-ai/benchflow), compatible with native \`task.md\` packages:

\`\`\`sh
uv tool install "benchflow>=0.6.3,<0.7"
\`\`\`

- An authenticated supported coding agent (the examples use Codex) and a model available to that agent. Verify locally with \`bench agent list\`.
- Run the commands from the **repository root**.

## Cases

| Task | Skill | Primary check |
| --- | --- | --- |
| \`test-refactoring\` | \`test-baseline-maintenance\` | Public behavior and existing tests remain valid after extracting a shared helper |
| \`test-duplicate-cleanup\` | \`test-baseline-maintenance\` | Remove redundant tests while detecting three separate state-guard mutations |
| \`docs-config-change\` | \`documentation-baseline-maintenance\` | Current docs match config keys/defaults and maintain canonical links |
| \`docs-duplicate-cleanup\` | \`documentation-baseline-maintenance\` | Preserve unique instructions/ADR while consolidating duplicate pages |

## Check and calibrate before A/B runs

\`\`\`sh
bench tasks check benchmark/tasks/test-refactoring
bench tasks check benchmark/tasks/test-duplicate-cleanup
bench tasks check benchmark/tasks/docs-config-change
bench tasks check benchmark/tasks/docs-duplicate-cleanup

# Run the held-out reference solution for each task; each should score 1.0.
bench eval run --tasks-dir benchmark/tasks/test-refactoring --agent oracle --sandbox docker
\`\`\`

Repeat the oracle command for the other three tasks before interpreting agent results. Task verifiers output a deterministic reward of 1 (pass) or 0 (fail) and diagnostic logs.

## A/B on the same task

Run from the root. For a test-maintenance task, stage **only** the intended skill:

\`\`\`sh
mkdir -p benchmark/.runtime/skills
cp -R test-baseline-maintenance benchmark/.runtime/skills/

# A: no skill
bench eval run --tasks-dir benchmark/tasks/test-refactoring \\
  --agent codex --model YOUR_MODEL --sandbox docker \\
  --skill-mode no-skill --jobs-dir benchmark/.runtime/jobs/test-refactoring-A

# B: with the single designated skill
bench eval run --tasks-dir benchmark/tasks/test-refactoring \\
  --agent codex --model YOUR_MODEL --sandbox docker \\
  --skill-mode with-skill --skills-dir benchmark/.runtime/skills \\
  --jobs-dir benchmark/.runtime/jobs/test-refactoring-B
\`\`\`

For documentation cases, clear \`benchmark/.runtime/skills/\` and stage **only** \`documentation-baseline-maintenance\`. Do not mount both skills indiscriminately: the experiment is intended to isolate each skill's incremental value. Use the same model, agent version, initial fixture, sandbox, and task prompt for both conditions. Run further trials before drawing stable conclusions; record the skill's Git commit SHA.

**Isolation caution:** Global skills, \`AGENTS.md\` rules, and system-level custom instructions may leak the tested policy into the no-skill condition. Disable or equalize those factors. Do not mount \`oracle/\` or \`verifier/\` into the agent workspace; BenchFlow owns those surfaces.

## What the binary reward does and does not measure

Verifiers check observable outcomes: functional behavior, distinct regression detection, correct documentation and retained historical information. They also set basic bounds against low-value growth. The 0/1 result is a **small MVP signal**, not a full measure of architecture quality, test maintainability, document readability, or cost.

Inspect the resulting diffs, agent trajectories, tool usage and residual risks as a second review step. Store raw results under \`benchmark/.runtime/\` (Git-ignored); share only sanitized, aggregated findings. No task runner, custom agent adapter, database, or web UI is included.
