import ast
import re
from pathlib import Path

root = Path("/app")
original = "import os\n\ndef payment_settings():\n    return {\n        \"retry_limit\": int(os.getenv(\"PAYMENT_RETRY_LIMIT\", \"5\")),\n        \"retry_delay_seconds\": int(os.getenv(\"PAYMENT_RETRY_DELAY_SECONDS\", \"2\")),\n    }\n"
assert (root / "app_config.py").read_text() == original, "Configuration code must not be changed"
docs = [root / "README.md", root / "docs/configuration.md", root / "docs/deploy.md"]
assert all(p.is_file() for p in docs)
combined = "\n".join(p.read_text() for p in docs)
assert "PAYMENT_MAX_RETRIES" not in combined and "RETRY_INTERVAL" not in combined, (
    "Current-state documentation still contains retired configuration keys"
)
config = docs[1].read_text()
deploy = docs[2].read_text()
for name, default in [("PAYMENT_RETRY_LIMIT", "5"), ("PAYMENT_RETRY_DELAY_SECONDS", "2")]:
    assert re.search(rf"{name}[^\n]*\b{default}\b", config), f"Missing {name} default {default}"
    assert f"export {name}={default}" in deploy, f"Deployment example misses {name}"
assert "(docs/configuration.md)" in docs[0].read_text(), "README no longer links to canonical configuration"
assert "(configuration.md)" in deploy, "Deployment guide lost the canonical configuration link"
markdown = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))
assert markdown == ["README.md", "docs/configuration.md", "docs/deploy.md"], (
    "Avoid unrelated new Markdown documents: " + str(markdown)
)
print("PASS: keys, defaults and deployment examples match implementation; canonical links preserved")
