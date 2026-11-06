import importlib.util
from pathlib import Path
import sys
import unittest

SPEC = importlib.util.spec_from_file_location(
    "compare_runtime_bytespace", Path(__file__).with_name("compare_runtime_bytespace.py")
)
comparison = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = comparison
SPEC.loader.exec_module(comparison)


class ComparisonTests(unittest.TestCase):
    def test_failed_head_is_not_reported_as_a_size_reduction(self):
        base = comparison.ReportData("success", 100, {}, None)
        head = comparison.ReportData("failed", None, {}, "compiler failed")
        report = comparison.build_report("Example", base, head, [])
        self.assertIn("Head compilation failed", report)
        self.assertIn("compiler failed", report)
        self.assertNotIn("Delta:", report)

    def test_missing_report_is_visible(self):
        success = comparison.ReportData("success", 100, {}, None)
        missing = comparison.ReportData("missing", None, {}, None)
        for base, head, name in [(success, missing, "Head"), (missing, success, "Base")]:
            with self.subTest(name=name):
                report = comparison.build_report("Example", base, head, [])
                self.assertIn(f"{name} runtime bytespace report is missing", report)
                self.assertNotIn("Delta:", report)

    def test_successful_comparison_retains_delta(self):
        base = comparison.ReportData("success", 100, {}, None)
        head = comparison.ReportData("success", 80, {}, None)
        self.assertIn("Delta: -20 bytes", comparison.build_report("Example", base, head, []))


if __name__ == "__main__":
    unittest.main()
