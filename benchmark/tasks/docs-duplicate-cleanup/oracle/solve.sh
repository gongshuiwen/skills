#!/usr/bin/env bash
set -euo pipefail
cat > /app/docs/setup.md <<'MD'
# Installation

Requires Python 3.12.

1. Set \`APP_SECRET\` to at least **32 characters**.
2. Before applying migrations, run \`python -m app migrate --check\`.
3. Run \`python -m app migrate\`.
4. Run \`python -m app serve\`.
MD
cat > /app/README.md <<'MD'
# Order Service

To get started, read the [Installation guide](docs/setup.md).
MD
rm /app/docs/setup-quick.md
