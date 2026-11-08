import re
from pathlib import Path

root = Path("/app")
assert (root / "docs/adr/0001-storage.md").read_text() == "# ADR 0001: SQLite storage\n\nStatus: Superseded\n\nWe originally used SQLite for local demos before adopting a separate database service.\nThis record explains the historical decision and must remain available.\n", (
    "Historical ADR was deleted or rewritten"
)
setup_file = root / "docs/setup.md"
readme_file = root / "README.md"
assert setup_file.is_file() and readme_file.is_file(), "Canonical documentation must remain"
assert not (root / "docs/setup-quick.md").exists(), "Duplicate quickstart should be consolidated"
instructions = setup_file.read_text()
readme = readme_file.read_text()
assert "Python 3.12" in instructions
assert "APP_SECRET" in instructions and re.search(r"32\s+characters", instructions, re.I), (
    "Unique security requirement was lost"
)
for command in ("python -m app migrate --check", "python -m app migrate", "python -m app serve"):
    assert command in instructions, f"Unique workflow detail lost: {command}"
assert "(docs/setup.md)" in readme and "setup-quick.md" not in readme, (
    "README navigation still points at a redundant guide"
)
md_files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.md"))
assert md_files == ["README.md", "docs/adr/0001-storage.md", "docs/setup.md"], (
    "Unexpected documentation footprint: " + str(md_files)
)
print("PASS: one canonical setup guide with unique instructions, working index and preserved ADR")
