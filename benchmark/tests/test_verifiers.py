"""Scorer calibration. Run from the repo root with Python 3.12 on Linux/WSL."""

import ast
import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BENCHMARK = Path(__file__).resolve().parents[1]


def load_checker(task):
    spec = importlib.util.spec_from_file_location(task, BENCHMARK / "tasks" / task / "verifier/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRICING = load_checker("test-refactoring")
DOCS = load_checker("docs-config-change")


class CandidateCase(unittest.TestCase):
    task = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app"
        shutil.copytree(BENCHMARK / "tasks" / self.task / "environment/project", self.root)
        script = (BENCHMARK / "tasks" / self.task / "oracle/solve.sh").read_text()
        result = subprocess.run(["bash", "-c", script.replace("/app", str(self.root))],
                                cwd=self.root, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def verify(self):
        checker = PRICING if self.task == "test-refactoring" else DOCS
        with contextlib.redirect_stdout(io.StringIO()):
            checker.verify(self.root)

    def append(self, name, text):
        path = self.root / name
        path.write_text(path.read_text() + "\n" + text)


class PricingScorerTests(CandidateCase):
    task = "test-refactoring"

    def test_oracle_and_original_four_regressions_pass(self):
        self.verify()

    def test_more_than_six_distinct_methods_pass(self):
        self.append("tests/test_pricing.py", '''
class AdditionalRules(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(quote_total([]), Decimal("0.00"))
    def test_zero_price(self):
        self.assertEqual(invoice_total([("0", 1)]), Decimal("0.00"))
    def test_round_once(self):
        self.assertEqual(quote_total([("0.004", 1), ("0.004", 1)]), Decimal("0.01"))
    def test_negative_price(self):
        with self.assertRaises(ValueError):
            invoice_total([("-1", 1)])
    def test_iterable(self):
        self.assertEqual(invoice_total(iter([("2", 3)])), Decimal("6.00"))
''')
        self.verify()

    def test_empty_suite_fails(self):
        (self.root / "tests/test_pricing.py").write_text("import unittest\n")
        with self.assertRaisesRegex(AssertionError, "nonempty"):
            self.verify()

    def test_only_skipped_tests_fail(self):
        path = self.root / "tests/test_pricing.py"
        path.write_text(path.read_text().replace("class PriceRulesTests", '@unittest.skip("skip")\nclass PriceRulesTests'))
        with self.assertRaisesRegex(AssertionError, "nonempty"):
            self.verify()

    def test_each_removed_original_contract_fails(self):
        path = self.root / "tests/test_pricing.py"
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                with self.subTest(removed=node.name):
                    lines = source.splitlines(keepends=True)
                    path.write_text("".join(lines[:node.lineno - 1] + lines[node.end_lineno:]))
                    with self.assertRaisesRegex(AssertionError, "regression went undetected"):
                        self.verify()

    def test_public_behavior_regression_fails(self):
        path = self.root / "pricing.py"
        path.write_text(path.read_text().replace('Decimal("0.95")', 'Decimal("0.90")'))
        with self.assertRaisesRegex(AssertionError, "Public behavior changed"):
            self.verify()

    def test_independent_helpers_fail(self):
        path = self.root / "pricing.py"
        source = path.read_text()
        helper = source[source.index("def _total"):source.index("def quote_total")]
        source += "\n" + helper.replace("_total", "_other_total")
        source = source.replace("def invoice_total(lines, member=False):\n    return _total", "def invoice_total(lines, member=False):\n    return _other_total")
        path.write_text(source)
        with self.assertRaisesRegex(AssertionError, "same internal implementation"):
            self.verify()


class DocumentationScorerTests(CandidateCase):
    task = "docs-config-change"

    def test_oracle_passes(self):
        self.verify()

    def test_explicit_retirement_note_passes(self):
        self.append("docs/configuration.md", "`PAYMENT_MAX_RETRIES` and `RETRY_INTERVAL` are not read by the implementation.\n")
        self.verify()

    def test_wrapped_migration_paragraph_passes(self):
        self.append("docs/deploy.md", "If your deployment still sets\n`PAYMENT_MAX_RETRIES` or `RETRY_INTERVAL`, replace those variables with\n`PAYMENT_RETRY_LIMIT` or `PAYMENT_RETRY_DELAY_SECONDS`; the old names\nare not read.\n")
        self.verify()

    def test_deprecated_heading_and_table_pass(self):
        self.append("docs/configuration.md", "## Deprecated variables\n\n| Retired key | Replacement |\n| --- | --- |\n| PAYMENT_MAX_RETRIES | PAYMENT_RETRY_LIMIT |\n| RETRY_INTERVAL | PAYMENT_RETRY_DELAY_SECONDS |\n")
        self.verify()

    def test_unmarked_stale_instructions_fail(self):
        self.append("docs/configuration.md", "Set PAYMENT_MAX_RETRIES to control payment retry attempts.\n")
        with self.assertRaisesRegex(AssertionError, "retired key"):
            self.verify()

    def test_obsolete_executable_example_fails(self):
        self.append("docs/deploy.md", "```sh\nexport PAYMENT_MAX_RETRIES=3\n```\n")
        with self.assertRaisesRegex(AssertionError, "configuration example"):
            self.verify()

    def test_negative_instruction_passes(self):
        self.append("docs/deploy.md", "Do not set PAYMENT_MAX_RETRIES or RETRY_INTERVAL.\n")
        self.verify()

    def test_explicit_historical_example_passes(self):
        self.append("docs/deploy.md", "## Migration\n\nBefore (obsolete, do not use):\n\n```sh\nexport PAYMENT_MAX_RETRIES=3\nexport RETRY_INTERVAL=10\n```\n")
        self.verify()

    def test_generic_migration_heading_does_not_excuse_old_commands(self):
        self.append("docs/deploy.md", "## Migration\n\n```sh\nexport PAYMENT_MAX_RETRIES=3\n```\n")
        with self.assertRaisesRegex(AssertionError, "configuration example"):
            self.verify()

    def test_unrelated_warning_does_not_excuse_stale_instruction(self):
        self.append("docs/configuration.md", "Deprecated variables have been removed.\n\n- PAYMENT_MAX_RETRIES: set to 3.\n")
        with self.assertRaisesRegex(AssertionError, "retired key"):
            self.verify()

    def test_one_warned_list_item_does_not_excuse_next(self):
        self.append("docs/configuration.md", "- PAYMENT_MAX_RETRIES is deprecated.\n- RETRY_INTERVAL: default 10.\n")
        with self.assertRaisesRegex(AssertionError, "retired key"):
            self.verify()

    def test_deprecated_section_context_does_not_leak(self):
        self.append("docs/configuration.md", "## Deprecated variables\n\nPAYMENT_MAX_RETRIES is obsolete.\n\n## Current settings\n\nRETRY_INTERVAL controls retries.\n")
        with self.assertRaisesRegex(AssertionError, "retired key"):
            self.verify()

    def test_wrong_default_fails(self):
        path = self.root / "docs/configuration.md"
        path.write_text(path.read_text().replace("5", "3"))
        with self.assertRaisesRegex(AssertionError, "default 5"):
            self.verify()

    def test_changed_configuration_code_fails(self):
        self.append("app_config.py", "# unrelated implementation change\n")
        with self.assertRaisesRegex(AssertionError, "must not be changed"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
