import ast
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

root = Path("/app")
sys.path.insert(0, str(root))
source = root.joinpath("pricing.py").read_text()
tree = ast.parse(source)
functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
helpers = {name for name in functions if name.startswith("_")}
assert helpers, "Expected a shared internal helper"
for name in ("quote_total", "invoice_total"):
    assert name in functions, f"Public API {name} is missing"
    calls = (node for node in ast.walk(functions[name]) if isinstance(node, ast.Call))
    assert any(isinstance(c.func, ast.Name) and c.func.id in helpers for c in calls), (
        f"{name} should delegate to shared logic"
    )
result = subprocess.run(
    [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
    cwd=root, text=True, capture_output=True, timeout=30,
)
assert result.returncode == 0, result.stdout + result.stderr
from pricing import quote_total, invoice_total
for public in (quote_total, invoice_total):
    assert public([]) == Decimal("0.00")
    assert public([("2.50", 2), ("0.10", 3)]) == Decimal("5.30")
    assert public([("20", 1)], member=True) == Decimal("19.00")
    assert public([("1.005", 1)]) == Decimal("1.01")
    for invalid in ([("2", 0)], [("-1", 1)]):
        try:
            public(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{public.__name__} accepted invalid input")
test_count = len([n for n in ast.walk(ast.parse((root / "tests/test_pricing.py").read_text()))
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")])
assert test_count <= 6, "The refactor added many low-value test cases"
print("PASS: public behavior preserved; duplicate calculation extracted; baseline tests valid")
