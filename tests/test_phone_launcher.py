"""Phone launcher tests using harmless child scripts in a copied fixture tree."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "pixel9-phone.sh"
ALLOWED_PROPERTIES = {
    "ro.product.model", "ro.product.device", "ro.build.version.release",
    "ro.build.id", "gsm.version.baseband",
}


class PhoneLauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="p9pf-phone-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        # Spaces and apostrophes catch accidental shell splitting/evaluation.
        package = self.root / "downloaded package's folder"
        scripts = package / "scripts"
        tools = package / "tools"
        scripts.mkdir(parents=True)
        tools.mkdir()
        self.launcher = scripts / "pixel9-phone.sh"
        shutil.copyfile(LAUNCHER, self.launcher)
        self.state = self.root / "private state's folder"
        self.downloads = self.root / "shared downloads"
        self.downloads.mkdir()
        self.calls = self.root / "calls.txt"
        self.argv = self.root / "core-argv.txt"
        self.props = self.root / "properties.txt"
        (scripts / "pixel9-csl-nrdc.sh").write_text(
            '#!/bin/sh\n'
            'printf "core\\n" >> "$CALL_LOG"\n'
            ': > "$CORE_ARGV"\n'
            'for arg do printf "%s\\n" "$arg" >> "$CORE_ARGV"; done\n'
            'mkdir -p "$P9PF_STATE_ROOT/run-stub"\n'
            'printf "PRIVATE_BACKUP_SENTINEL\\n" > "$P9PF_STATE_ROOT/run-stub/backup.tsv"\n'
            'printf "PRIVATE_REPLY_SENTINEL\\n" > "$P9PF_STATE_ROOT/run-stub/reply-1.txt"\n'
            'printf "PRIVATE_JOURNAL_SENTINEL\\n" > "$P9PF_STATE_ROOT/run-stub/touched.tsv"\n'
            'printf "NV-MOCK-SUMMARY\\n"\n'
            'exit "${STUB_NV_STATUS:-0}"\n'
        )
        (tools / "audit_nr_carrier_config.sh").write_text(
            '#!/bin/sh\n'
            'printf "carrier\\n" >> "$CALL_LOG"\n'
            'printf "PRIVATE_FULL_DUMP_SENTINEL\\n" > "$P9PF_STATE_ROOT/full-dump.txt"\n'
            'printf "Phone Id = 0\\ncarrier_nr_availabilities_int_array = [1, 2]\\n"\n'
            'exit "${STUB_CARRIER_STATUS:-0}"\n'
        )
        helpers = self.root / "bin"
        helpers.mkdir()
        (helpers / "id").write_text(
            '#!/bin/sh\n[ "$1" = -u ] || exit 1\nprintf "%s\\n" "${FAKE_UID:-0}"\n'
        )
        (helpers / "getprop").write_text(
            '#!/bin/sh\nprintf "%s\\n" "$1" >> "$PROP_CALLS"\n'
            'printf "safe:%s\\n" "$1"\n'
        )
        # If the launcher unexpectedly tries escalation or ADB, fail visibly.
        for name in ("su", "adb"):
            (helpers / name).write_text(
                '#!/bin/sh\nprintf "UNEXPECTED_ESCALATION_OR_ADB\\n" >> "$CALL_LOG"\nexit 99\n'
            )
        for helper in helpers.iterdir():
            helper.chmod(0o700)
        self.env = dict(
            os.environ,
            PATH=str(helpers) + os.pathsep + os.environ["PATH"],
            P9PF_STATE_ROOT=str(self.state), P9PF_DOWNLOAD_DIR=str(self.downloads),
            CALL_LOG=str(self.calls), CORE_ARGV=str(self.argv), PROP_CALLS=str(self.props),
        )
        self.shell = shutil.which("dash") or "/bin/sh"

    def run_launcher(self, *args, **overrides):
        return subprocess.run([self.shell, str(self.launcher), *args],
                              env=dict(self.env, **overrides), capture_output=True,
                              text=True, timeout=5)

    def assert_success(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def reports(self):
        return list(self.downloads.glob("P9PF-NRDC-report-*.txt"))

    def test_no_arguments_runs_both_read_only_audits(self):
        completed = self.run_launcher()
        self.assert_success(completed)
        self.assertEqual(self.argv.read_text().splitlines(),
                         ["audit", "--slot", "both", "--state-root", str(self.state)])
        self.assertEqual(self.calls.read_text().splitlines(), ["core", "carrier"])
        self.assertIn("NV-MOCK-SUMMARY", completed.stdout)
        self.assertIn("carrier_nr_availabilities_int_array = [1, 2]", completed.stdout)
        self.assertEqual(len(self.reports()), 1)

    def test_enable_both_preserves_exact_argv_in_paths_with_spaces(self):
        self.assert_success(self.run_launcher("enable-both"))
        self.assertEqual(self.argv.read_text().splitlines(),
                         ["enable", "--slot", "both", "--state-root", str(self.state)])

    def test_restore_preserves_exact_directory_argument(self):
        backup_dir = self.root / "saved backup's path with spaces"
        backup_dir.mkdir()
        self.assert_success(self.run_launcher("restore", str(backup_dir)))
        self.assertEqual(self.argv.read_text().splitlines(),
                         ["restore", str(backup_dir), "--state-root", str(self.state)])

    def test_nv_failure_still_collects_carrier_and_preserves_exit_status(self):
        completed = self.run_launcher("audit", STUB_NV_STATUS="7")
        self.assertEqual(completed.returncode, 7, completed.stdout + completed.stderr)
        self.assertEqual(self.calls.read_text().splitlines(), ["core", "carrier"])
        report = self.reports()[0].read_text()
        self.assertIn("NV_exit_code=7", report)
        self.assertIn("CarrierConfig_exit_code=0", report)
        self.assertIn("carrier_nr_availabilities_int_array", report)

    def test_carrier_failure_is_reported_and_propagated(self):
        completed = self.run_launcher("audit", STUB_CARRIER_STATUS="9")
        self.assertEqual(completed.returncode, 9, completed.stdout + completed.stderr)
        self.assertIn("CarrierConfig_exit_code=9", self.reports()[0].read_text())

    def test_public_report_contains_only_summary_config_and_allowed_properties(self):
        self.assert_success(self.run_launcher("audit"))
        public = self.reports()
        self.assertEqual(len(public), 1)
        report = public[0].read_text()
        self.assertIn("NV-MOCK-SUMMARY", report)
        self.assertIn("carrier_nr_availabilities_int_array = [1, 2]", report)
        requested = set(self.props.read_text().splitlines())
        self.assertEqual(requested, ALLOWED_PROPERTIES)
        for prop in ALLOWED_PROPERTIES:
            self.assertIn(f"{prop}=safe:{prop}", report)
        for sentinel in ("PRIVATE_BACKUP_SENTINEL", "PRIVATE_REPLY_SENTINEL",
                         "PRIVATE_JOURNAL_SENTINEL", "PRIVATE_FULL_DUMP_SENTINEL"):
            self.assertNotIn(sentinel, report)
        self.assertEqual(list(self.downloads.iterdir()), public,
                         "No raw files or state tree may be exported beside the report")
        self.assertTrue((self.state / "run-stub/backup.tsv").is_file())
        self.assertTrue((self.state / "run-stub/reply-1.txt").is_file())

    def test_missing_download_directory_fails_with_private_report_preserved(self):
        missing = self.root / "missing shared directory"
        completed = self.run_launcher("audit", P9PF_DOWNLOAD_DIR=str(missing))
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(missing.exists())
        private_reports = list(self.state.glob("phone-*/report.txt"))
        self.assertEqual(len(private_reports), 1)
        self.assertIn("NV-MOCK-SUMMARY", private_reports[0].read_text())
        self.assertIn("private report preserved", completed.stderr)

    def test_invalid_modes_or_missing_restore_directory_do_not_invoke_children(self):
        for arguments in (("unknown",), ("restore",), ("enable-both", "extra"),
                          ("audit", "extra")):
            with self.subTest(arguments=arguments):
                completed = self.run_launcher(*arguments)
                self.assertNotEqual(completed.returncode, 0)
                self.assertFalse(self.calls.exists())
                self.assertFalse(self.state.exists())

    def test_help_is_available_without_root_and_never_runs_children(self):
        completed = self.run_launcher("--help", FAKE_UID="1000")
        self.assert_success(completed)
        self.assertIn("Run from a root terminal", completed.stdout)
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.state.exists())

    def test_non_root_audit_stops_without_escalation_or_children(self):
        completed = self.run_launcher("audit", FAKE_UID="1000")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Type su", completed.stderr)
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main()
