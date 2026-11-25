import unittest

from deployment_config import validate_cors_origins


class DeploymentConfigTests(unittest.TestCase):
    def test_production_requires_explicit_origins(self):
        with self.assertRaisesRegex(ValueError, "wildcard is forbidden"):
            validate_cors_origins("production", ["*"])

    def test_production_accepts_explicit_origins(self):
        self.assertEqual(
            validate_cors_origins("production", [" https://example.com ", ""]),
            ["https://example.com"],
        )

    def test_production_rejects_wildcard_even_with_trusted_origin(self):
        with self.assertRaisesRegex(ValueError, "wildcard is forbidden"):
            validate_cors_origins("production", ["https://example.com", "*"])

    def test_empty_production_origins_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "wildcard is forbidden"):
            validate_cors_origins("production", [" ", ""])
    def test_development_can_keep_wildcard_default(self):
        self.assertEqual(validate_cors_origins("development", ["*"]), ["*"])


if __name__ == "__main__":
    unittest.main()
