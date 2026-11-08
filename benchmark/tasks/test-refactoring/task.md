---
schema_version: '1.3'
metadata:
  author_name: gongshuiwen
  difficulty: medium
  difficulty_explanation: A duplicated calculation must be consolidated without changing public behavior or inflating the test baseline.
  category: software-engineering
  subcategory: maintenance
  category_confidence: high
  task_type:
    - implementation
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

Refactor the repeated calculation logic in `/app/pricing.py` into one shared internal implementation. Keep the public functions `quote_total` and `invoice_total` and preserve their behavior, including rounding, membership discounts and invalid input handling. Keep relevant regression tests aligned with the change and run appropriate checks.
