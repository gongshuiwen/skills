import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCORING_VERSION = 2

# The four independent contracts exercised by the original regression suite.
# Override public entry points so mutation detection is independent of how a
# candidate names or structures its shared internal implementation.
MUTANT_BODY = '''
from decimal import Decimal as _D, ROUND_HALF_EVEN as _EVEN, ROUND_HALF_UP as _UP
def {public}(lines, member=False):
    subtotal = _D("0")
    for price, quantity in lines:
        value = _D(str(price))
        if {guard}:
            raise ValueError("invalid order line")
        subtotal += {amount}
    if {discount}:
        subtotal *= _D("0.95")
    return subtotal.quantize(_D("0.01"), rounding={rounding})
'''
MUTATIONS = {
    "quote_quantity_multiplication": dict(public="quote_total", guard="quantity <= 0 or value < 0",
                                          amount="value", discount="member", rounding="_UP"),
    "invoice_member_discount": dict(public="invoice_total", guard="quantity <= 0 or value < 0",
                                    amount="value * quantity", discount="False", rounding="_UP"),
    "quote_invalid_quantity": dict(public="quote_total", guard="value < 0",
                                   amount="value * quantity", discount="member", rounding="_UP"),
    "invoice_half_up_rounding": dict(public="invoice_total", guard="quantity <= 0 or value < 0",
                                     amount="value * quantity", discount="member", rounding="_EVEN"),
}
SUITE_RUNNER = '''
import json
import unittest
from pathlib import Path
suite = unittest.defaultTestLoader.discover("tests")
result = unittest.TextTestRunner(verbosity=2).run(suite)
Path("_suite_result.json").write_text(json.dumps({
    "run": result.testsRun, "skipped": len(result.skipped),
    "failures": len(result.failures), "errors": len(result.errors),
    "successful": result.wasSuccessful(),
}))
'''


def run_suite(root, source):
    with tempfile.TemporaryDirectory() as tmp:
        destination = Path(tmp) / "project"
        shutil.copytree(root, destination, ignore=shutil.ignore_patterns("__pycache__", ".git", ".venv"))
        (destination / "pricing.py").write_text(source)
        result = subprocess.run(
            [sys.executable, "-B", "-c", SUITE_RUNNER], cwd=destination,
            text=True, capture_output=True, timeout=30,
        )
        assert result.returncode == 0, "Test runner failed:\n" + result.stdout + result.stderr
        return json.loads((destination / "_suite_result.json").read_text()), result.stdout + result.stderr


def shared_helpers(source):
    functions = {node.name: node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}

    def reachable(name, visited=None):
        visited = set() if visited is None else visited
        if name not in functions or name in visited:
            return visited
        visited.add(name)
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                reachable(node.func.id, visited)
        return visited

    for name in ("quote_total", "invoice_total"):
        assert name in functions, f"Public API {name} is missing"
    shared = reachable("quote_total") & reachable("invoice_total")
    assert any(name.startswith("_") for name in shared), "Both public APIs must use the same internal implementation"


def verify_behavior(root):
    # Avoid reusing imported modules across independent candidate workspaces.
    program = '''
from decimal import Decimal, ROUND_HALF_UP
from pricing import quote_total, invoice_total
cases = [[], [("2.50", 2), ("0.10", 3)], [("5.00", 2), ("2.25", 1)],
         [("20", 1)], [("1.005", 1)], [("0.004", 1), ("0.004", 1)],
         [("0", 1)], [(Decimal("0.125"), 3)], [(0.1, 3)]]
for public in (quote_total, invoice_total):
    for lines in cases:
        for member in (False, True):
            expected = sum((Decimal(str(price)) * quantity for price, quantity in lines), Decimal("0"))
            if member:
                expected *= Decimal("0.95")
            expected = expected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            for value in (lines, iter(lines)):
                actual = public(value, member)
                assert isinstance(actual, Decimal) and actual == expected and actual.as_tuple().exponent == -2, (public.__name__, lines, member, actual, expected)
    for invalid in ([("2", 0)], [("2", -1)], [("-1", 1)], [("1", 1), ("2", 0)]):
        for member in (False, True):
            try:
                public(invalid, member=member)
            except ValueError:
                pass
            else:
                raise AssertionError(f"{public.__name__} accepted invalid input")
'''
    result = subprocess.run([sys.executable, "-B", "-c", program], cwd=root,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, "Public behavior changed:\n" + result.stdout + result.stderr


def verify(root):
    source = (root / "pricing.py").read_text()
    shared_helpers(source)
    verify_behavior(root)
    baseline, output = run_suite(root, source)
    assert baseline["run"] > baseline["skipped"], "Expected a nonempty, active regression suite"
    assert baseline["successful"], "The implementation must pass its regression suite:\n" + output
    for name, settings in MUTATIONS.items():
        result, output = run_suite(root, source + MUTANT_BODY.format(**settings))
        assert result["run"] > result["skipped"], f"No active tests for {name}"
        assert not result["successful"], f"An original regression went undetected: {name}"
    print(f"PASS v{SCORING_VERSION}: shared implementation; public behavior preserved; "
          f"{baseline['run']} test methods; 4 original regression mutations detected")


if __name__ == "__main__":
    verify(Path("/app"))
