---
schema_version: '1.3'
metadata:
  author_name: gongshuiwen
  difficulty: medium
  difficulty_explanation: Duplicated onboarding docs contain unique instructions and a historical record that must survive consolidation.
  category: software-engineering
  subcategory: maintenance
  category_confidence: high
  task_type:
    - transformation
  modality:
    - source-code
  interface:
    - terminal
    - python
  skill_type:
    - domain-procedure
  tags:
    - maintenance
    - baseline
verifier:
  type: test-script
  timeout_sec: 180.0
agent:
  timeout_sec: 900.0
environment:
  network_mode: no-network
  build_timeout_sec: 600.0
  os: linux
  cpus: 1
  memory_mb: 2048
  storage_mb: 2048
---

The order service has overlapping onboarding pages in `/app/docs/setup.md` and `/app/docs/setup-quick.md`, plus README navigation to both. Consolidate them into a clear, maintainable entry point while preserving all unique instructions and the historical decision record in `docs/adr/0001-storage.md`. Verify links and avoid unnecessary documentation growth.
