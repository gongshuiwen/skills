---
schema_version: '1.3'
metadata:
  author_name: gongshuiwen
  difficulty: medium
  difficulty_explanation: An overgrown state-machine test suite must be simplified without weakening distinct error-mode detection.
  category: software-engineering
  subcategory: maintenance
  category_confidence: high
  task_type:
    - optimization
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

The regression suite in `/app/tests/test_workflow.py` contains repeated cases and has become expensive to maintain. Consolidate redundant cases or fixtures while protecting the important order-state transitions and rejection rules. Keep the behavior of `/app/workflow.py` unchanged and run the relevant test suite.
