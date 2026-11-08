import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path("/app")
baseline = "class Order:\n    def __init__(self):\n        self.state = \"draft\"\n\n    def approve(self):\n        if self.state != \"draft\":\n            raise ValueError(\"only drafts may be approved\")\n        self.state = \"approved\"\n        return self.state\n\n    def ship(self):\n        if self.state != \"approved\":\n            raise ValueError(\"only approved orders may ship\")\n        self.state = \"shipped\"\n        return self.state\n\n    def cancel(self):\n        if self.state == \"shipped\":\n            raise ValueError(\"shipped orders cannot be cancelled\")\n        self.state = \"cancelled\"\n        return self.state\n\n"
source = (root / "workflow.py").read_text()
assert source == baseline, "Do not change business implementation in this cleanup task"

tests_path = root / "tests/test_workflow.py"
tree = ast.parse(tests_path.read_text())
count = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
            for n in ast.walk(tree))
assert 1 <= count <= 8, f"Expected meaningful deduplication, got {count} test methods"

def suite_with(source_text):
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp)
        (dest / "workflow.py").write_text(source_text)
        shutil.copytree(root / "tests", dest / "tests", ignore=shutil.ignore_patterns("__pycache__"))
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=dest, capture_output=True, text=True, timeout=30,
        )
        return result.returncode, result.stdout + result.stderr

status, output = suite_with(source)
assert status == 0, "The preserved implementation must pass all tests:\n" + output
mutants = [
    'if self.state != "draft":',
    'if self.state != "approved":',
    'if self.state == "shipped":',
]
for guard in mutants:
    assert source.count(guard) == 1, "Unexpected baseline source"
    mutated = source.replace(guard, "if False:", 1)
    status, output = suite_with(mutated)
    assert status != 0, "A distinct order-state regression went undetected: " + guard
print(f"PASS: {count} test methods; 3 independently detected state guard regressions")
