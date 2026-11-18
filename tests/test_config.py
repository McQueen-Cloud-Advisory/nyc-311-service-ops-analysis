"""Regression cases for invalid configuration that ordinary JSON parsing accepts."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from nyc311.contracts import REPO_ROOT
from scripts.validate_config import check_example_contracts, read_json


class ConfigurationTests(unittest.TestCase):
    def test_ambiguous_or_nonfinite_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            for content in ('{"limit": 1, "limit": 2}', '{"nested": {"x": 1, "x": 2}}',
                            '{"limit": NaN}', '{"limit": Infinity}', '{"limit": -Infinity}'):
                with self.subTest(content=content):
                    path.write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        read_json(path)

    def copy_examples(self, directory):
        root = Path(directory)
        for relative in ("config/demo.json", "config/cloud.example.json", "infra/gcp.example.json",
                         "data/targets/demo_targets.csv"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / relative, destination)
        return root

    def test_mismatched_cloud_datasets_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_examples(directory)
            path = root / "config/cloud.example.json"
            config = read_json(path)
            config["reporting_dataset"] = "different_reporting"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "disagree on dataset IDs"):
                check_example_contracts(root)

    def test_boolean_query_limit_is_not_a_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_examples(directory)
            path = root / "config/cloud.example.json"
            config = read_json(path)
            config["maximum_bytes_billed"] = True
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "maximum_bytes_billed"):
                check_example_contracts(root)

    def test_targets_cannot_point_outside_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.copy_examples(directory)
            path = root / "config/demo.json"
            config = read_json(path)
            config["targets_csv"] = "../outside.csv"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "inside the checkout"):
                check_example_contracts(root)


if __name__ == "__main__":
    unittest.main()
