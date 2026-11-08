---
schema_version: '1.3'
metadata:
  author_name: gongshuiwen
  difficulty: medium
  difficulty_explanation: Configuration guidance is stale across an authoritative guide and deployment snippets.
  category: software-engineering
  subcategory: maintenance
  category_confidence: high
  task_type:
    - repair
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

The payment service configuration is correct in `/app/app_config.py`, but some project documentation describes old environment variables and default values. Update the relevant current-state documentation so that it accurately describes the implementation and can be used for deployment. Keep the configuration implementation unchanged.
