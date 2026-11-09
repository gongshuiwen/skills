import re
from pathlib import Path

SCORING_VERSION = 2
RETIRED_KEYS = ("PAYMENT_MAX_RETRIES", "RETRY_INTERVAL")
RETIRED_CONTEXT = re.compile(
    r"\b(?:deprecated|retired|obsolete|unsupported|ignored|legacy|formerly|previously)\b"
    r"|\bno\s+longer\b|\bnot\s+(?:read|used|supported|recognized)\b"
    r"|\b(?:replace|migrat\w*)\b|\bdo\s+not\s+(?:use|set)\b"
    r"|旧变量|旧配置|已废弃|已停用|不再|迁移|替换",
    re.IGNORECASE,
)
HISTORICAL_EXAMPLE = re.compile(
    r"\b(?:deprecated|retired|obsolete|legacy|formerly|previously|before)\b"
    r"|\bold\s+(?:names?|keys?|variables?|examples?|settings?)\b"
    r"|\bdo\s+not\s+(?:use|set|run)\b|旧变量|旧配置|已废弃|已停用|不再",
    re.IGNORECASE,
)


def check_retired_mentions(text, path):
    """Allow explicit migration prose; reject obsolete active settings.

    Check paragraphs, list items and table rows separately: one warning elsewhere
    on a page cannot excuse a stale instruction. A migration/deprecation heading
    supplies context only to its own section. Old executable examples also need
    an explicit historical/negative label, not just a generic migration heading.
    """
    heading_context = []
    paragraph = []
    fenced = False
    preceding_prose = ""

    def check(block, executable=False):
        if not any(re.search(rf"\b{key}\b", block) for key in RETIRED_KEYS):
            return
        assignment = any(re.search(rf"\b{key}\s*=", block) for key in RETIRED_KEYS)
        active_command = any(re.search(rf"\b(?:export|set|setenv)\s+{key}\b", block, re.I) for key in RETIRED_KEYS)
        context = " ".join(value for _, value in heading_context) + " " + block
        if executable:
            context += " " + preceding_prose
        if executable or assignment or active_command:
            assert HISTORICAL_EXAMPLE.search(context), (
                f"{path}: retired key used in an active configuration example: {block}"
            )
        assert RETIRED_CONTEXT.search(context), f"{path}: retired key lacks explicit migration/deprecation context: {block}"

    def flush():
        nonlocal preceding_prose
        if paragraph:
            block = "\n".join(paragraph)
            check(block, executable=fenced)
            preceding_prose = "" if fenced else block
            paragraph.clear()

    for line in text.splitlines():
        heading = re.match(r"^(#{1,6})\s+(.+)", line)
        if line.lstrip().startswith(("```", "~~~")):
            flush()
            fenced = not fenced
        elif fenced:
            paragraph.append(line)
        elif heading:
            flush()
            preceding_prose = ""
            level = len(heading[1])
            while heading_context and heading_context[-1][0] >= level:
                heading_context.pop()
            heading_context.append((level, heading[2]))
            check(heading[2])
        elif not line.strip():
            flush()
        elif re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|\|)", line):
            flush()
            paragraph.append(line)
        else:
            paragraph.append(line)
    flush()


def verify(root):
    original = "import os\n\ndef payment_settings():\n    return {\n        \"retry_limit\": int(os.getenv(\"PAYMENT_RETRY_LIMIT\", \"5\")),\n        \"retry_delay_seconds\": int(os.getenv(\"PAYMENT_RETRY_DELAY_SECONDS\", \"2\")),\n    }\n"
    assert (root / "app_config.py").read_text() == original, "Configuration code must not be changed"
    docs = [root / "README.md", root / "docs/configuration.md", root / "docs/deploy.md"]
    assert all(path.is_file() for path in docs)
    for path in docs:
        check_retired_mentions(path.read_text(), path.relative_to(root))
    config = docs[1].read_text()
    deploy = docs[2].read_text()
    for name, default in [("PAYMENT_RETRY_LIMIT", "5"), ("PAYMENT_RETRY_DELAY_SECONDS", "2")]:
        assert re.search(rf"\b{name}\b[^\n]*\b{default}\b", config), f"Missing {name} default {default}"
        assert re.search(rf"^\s*export\s+{name}\s*=\s*['\"]?{default}['\"]?\s*$", deploy, re.M), f"Deployment example misses {name}"
    assert "(docs/configuration.md)" in docs[0].read_text(), "README no longer links to canonical configuration"
    assert "(configuration.md)" in deploy, "Deployment guide lost the canonical configuration link"
    markdown = sorted(path.relative_to(root).as_posix() for path in root.rglob("*.md"))
    assert markdown == ["README.md", "docs/configuration.md", "docs/deploy.md"], (
        "Avoid unrelated new Markdown documents: " + str(markdown)
    )
    print(f"PASS v{SCORING_VERSION}: keys, defaults and active examples match implementation; "
          "explicit migration notes allowed; canonical links preserved")


if __name__ == "__main__":
    verify(Path("/app"))
