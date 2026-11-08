#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
config = Path("/app/docs/configuration.md")
config.write_text("""# Configuration

Payment retries are controlled by:

- `PAYMENT_RETRY_LIMIT`: number of attempts; default `5`.
- `PAYMENT_RETRY_DELAY_SECONDS`: delay in seconds; default `2`.

These settings are loaded from the environment when the service starts.
""")
Path("/app/docs/deploy.md").write_text("""# Deployment

Set payment retry values in the service environment:

```sh
export PAYMENT_RETRY_LIMIT=5
export PAYMENT_RETRY_DELAY_SECONDS=2
```

See [Configuration](configuration.md) for parameter meanings.
""")
PY
