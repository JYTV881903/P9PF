"""Check the on-device filter with synthetic output; no phone is contacted."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "audit_nr_carrier_config.sh"


@unittest.skipUnless(shutil.which("bash"), "Host fixture needs bash pipefail")
class CarrierConfigFilterTests(unittest.TestCase):
    def run_filter(self, text, status=0):
        with tempfile.TemporaryDirectory(prefix="carrier-filter-test-") as directory:
            root = Path(directory)
            # Payload is data in its own file, never interpolated into executable code.
            (root / "payload").write_text(text)
            (root / "dumpsys").write_text(
                '#!/bin/sh\n[ "$1" = carrier_config ] || exit 9\n'
                'cat "$TEST_CARRIER_PAYLOAD"\nexit "$TEST_CARRIER_EXIT"\n'
            )
            (root / "dumpsys").chmod(0o700)
            environment = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                               TEST_CARRIER_PAYLOAD=str(root / "payload"), TEST_CARRIER_EXIT=str(status))
            return subprocess.run(["bash", str(SCRIPT)], env=environment,
                                  capture_output=True, text=True, timeout=5)

    def test_retains_phone_and_layer_context_without_unrelated_data(self):
        result = self.run_filter(
            "Default Values from CarrierConfigManager:\n"
            "  carrier_nr_availabilities_int_array = [1, 2]\n"
            "  unrelated_secret = PRIVATE_MARKER\n"
            "Phone Id = 0\n"
            "  mConfigFromDefaultApp :\n"
            "    carrier_nr_availabilities_int_array = [1]\n"
            "  mConfigFromCarrierApp :\n"
            "  mPersistentOverrideConfigs :\n"
            "  mOverrideConfigs :\n"
            "    additional_nr_advanced_bands_int_array = [257]\n"
            "Phone Id = 1\n"
            "  mConfigFromDefaultApp :\n"
            "    carrier_nr_availabilities_int_array = [1, 2]\n"
            "mNoSimConfig :\n"
            "  carrier_nr_availabilities_int_array = [1]\n"
            "Log: private operator/account context PRIVATE_MARKER\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for label in ("Phone Id = 0", "Phone Id = 1", "mConfigFromDefaultApp",
                      "mConfigFromCarrierApp", "mPersistentOverrideConfigs", "mOverrideConfigs",
                      "mNoSimConfig", "Default Values from CarrierConfigManager"):
            self.assertIn(label, result.stdout)
        self.assertIn("carrier_nr_availabilities_int_array = [1]", result.stdout)
        self.assertNotIn("PRIVATE_MARKER", result.stdout)
        self.assertNotIn("unrelated_secret", result.stdout)

    def test_dump_failure_is_not_hidden_by_matching_permission_line(self):
        result = self.run_filter("Permission Denial: test fixture\n", status=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Permission Denial:", result.stdout)

    def test_no_matching_policy_is_not_success(self):
        result = self.run_filter("unrelated_key = OTHER_PRIVATE_MARKER\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("OTHER_PRIVATE_MARKER", result.stdout)


if __name__ == "__main__":
    unittest.main()
