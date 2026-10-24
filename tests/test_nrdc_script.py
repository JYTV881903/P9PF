"""Host-only PTY tests; no real Android device or modem is accessed."""

from __future__ import annotations

import os
from pathlib import Path
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import termios
import threading
import time
import tty
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pixel9-csl-nrdc.sh"
MAIN = "!NRCOMMON.NrDcSupport"
DS = "!NRCOMMON.NrDcSupport_DS"
GET = re.compile(r'^AT\+GOOGGETNV="(!NRCOMMON\.NrDcSupport(?:_DS)?)"$')
SET = re.compile(r'^AT\+GOOGSETNV="(!NRCOMMON\.NrDcSupport(?:_DS)?)",0,"(00|01)"$')


def get_response(key: str, value: str) -> bytes:
    return f'\r\n+GOOGGETNV: "{key}",0,"{value}"\r\n\r\nOK\r\n'.encode()


class Modem:
    """Only emulate the two declared NRDC keys, with CR-framed commands."""

    def __init__(self, values=None, intercept=None, before_set=None):
        self.values = dict(values or {MAIN: "00", DS: "00"})
        self.intercept = intercept
        self.before_set = before_set
        self.commands = []
        self.raw_commands = []
        self.errors = []
        self.first_command = threading.Event()
        self.stop = threading.Event()
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        self.port = os.ttyname(self.slave)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        pending = bytearray()
        try:
            while not self.stop.is_set():
                readable, _, _ = select.select([self.master], [], [], 0.05)
                if not readable:
                    continue
                data = os.read(self.master, 4096)
                pending.extend(data)
                while b"\r" in pending:
                    raw, _, remaining = pending.partition(b"\r")
                    pending[:] = remaining
                    self.raw_commands.append(bytes(raw))
                    if b"\n" in raw:
                        raise AssertionError("Command used LF; modem commands require CR only")
                    command = raw.decode("ascii")
                    if b"\r" in pending:
                        raise AssertionError("Commands were pipelined before the prior response")
                    self.commands.append(command)
                    self.first_command.set()
                    response = self._respond(command)
                    if response is not None:
                        os.write(self.master, response)
        except BaseException as exc:
            self.errors.append(exc)

    def _respond(self, command):
        if self.intercept is not None:
            result = self.intercept(self, command)
            if result is not NotImplemented:
                return result
        match = GET.fullmatch(command)
        if match:
            return get_response(match[1], self.values[match[1]])
        match = SET.fullmatch(command)
        if match:
            key, value = match.groups()
            if self.before_set is not None:
                self.before_set(key, value)
            self.values[key] = value
            return b"\r\nOK\r\n"
        # Do not acknowledge arbitrary command strings or diagnostics.
        return b"\r\nERROR\r\n"

    def close(self):
        self.stop.set()
        self.thread.join(2)
        os.close(self.master)
        os.close(self.slave)


class NRDCScriptTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), f"Missing script: {SCRIPT}")
        self.tmp = tempfile.TemporaryDirectory(prefix="p9pf-nrdc-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        helpers = self.root / "bin"
        helpers.mkdir()
        (helpers / "id").write_text('#!/bin/sh\n[ "$1" = "-u" ] && { echo 0; exit 0; }\nexit 1\n')
        (helpers / "getprop").write_text(
            '#!/bin/sh\ncase "$1" in\n'
            'ro.product.device|ro.product.vendor.device) echo comet;;\n'
            'ro.product.model) echo "Pixel 9 Pro Fold";;\n'
            'ro.product.manufacturer|ro.product.brand) echo Google;;\n'
            'ro.build.version.release) echo 16;;\n'
            'ro.build.version.sdk) echo 36;;\n'
            '*) exit 0;;\nesac\n'
        )
        for helper in helpers.iterdir():
            helper.chmod(0o700)
        self.env = dict(os.environ, PATH=str(helpers) + os.pathsep + os.environ["PATH"])
        self.shell = shutil.which("dash") or "/bin/sh"

    def modem(self, **kwargs):
        result = Modem(**kwargs)
        self.addCleanup(result.close)
        return result

    def command(self, modem, mode="audit", extra=()):
        return [self.shell, str(SCRIPT), *([mode] if mode is not None else []), *extra,
                "--port", modem.port, "--state-root", str(self.state), "--timeout", "1"]

    def run_script(self, modem, mode="audit", extra=()):
        completed = subprocess.run(self.command(modem, mode, extra), env=self.env,
                                   capture_output=True, text=True, timeout=20)
        if modem.errors:
            raise modem.errors[0]
        return completed

    def backups(self):
        results = []
        for path in self.state.rglob("*"):
            if path.is_file():
                try:
                    contents = path.read_text()
                except (UnicodeError, OSError):
                    continue
                if contents.startswith("P9PF_NRDC_BACKUP_V1\n"):
                    results.append((path, contents))
        return results

    def assert_backup_precedes_set(self, expected):
        def check(key, value):
            candidates = self.backups()
            self.assertEqual(len(candidates), 1, "Complete backup must exist before SET")
            backup, contents = candidates[0]
            for original_key, original_value in expected.items():
                self.assertIn(f"{original_key}\t0\t{original_value}\n", contents)
            touched = backup.parent / "touched.tsv"
            self.assertTrue(touched.is_file(), "Touched journal must precede SET")
            self.assertIn(f"{key}\t0\t{expected[key]}\n", touched.read_text())
        return check

    def assert_success(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def assert_failed_without_write(self, modem, completed):
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertFalse(any(SET.fullmatch(cmd) for cmd in modem.commands), modem.commands)

    def test_audit_reads_exact_keys_and_never_writes(self):
        modem = self.modem()
        completed = self.run_script(modem, extra=("--slot", "both"))
        self.assert_success(completed)
        self.assertIn(f'AT+GOOGGETNV="{MAIN}"', modem.commands)
        self.assertIn(f'AT+GOOGGETNV="{DS}"', modem.commands)
        self.assertFalse(any(SET.fullmatch(cmd) for cmd in modem.commands))
        # Audit may probe documented optional keys, which this emulator rejects.
        self.assertTrue(all(re.fullmatch(r'AT\+GOOGGETNV="[^"\r\n]+"', cmd)
                            for cmd in modem.commands), modem.commands)

    def test_no_mode_defaults_to_read_only_audit(self):
        modem = self.modem()
        self.assert_success(self.run_script(modem, None))
        self.assertTrue(modem.commands)
        self.assertFalse(any(SET.fullmatch(cmd) for cmd in modem.commands))

    def test_enable_both_backs_up_before_write_and_reads_back(self):
        originals = {MAIN: "00", DS: "00"}
        modem = self.modem(values=originals, before_set=self.assert_backup_precedes_set(originals))
        completed = self.run_script(modem, "enable", ("--slot", "both"))
        self.assert_success(completed)
        self.assertEqual(modem.values, {MAIN: "01", DS: "01"})
        sets = [cmd for cmd in modem.commands if SET.fullmatch(cmd)]
        self.assertEqual(sets, [f'AT+GOOGSETNV="{MAIN}",0,"01"',
                                f'AT+GOOGSETNV="{DS}",0,"01"'])
        for key in originals:
            set_index = modem.commands.index(f'AT+GOOGSETNV="{key}",0,"01"')
            self.assertIn(f'AT+GOOGGETNV="{key}"', modem.commands[:set_index])
            self.assertIn(f'AT+GOOGGETNV="{key}"', modem.commands[set_index + 1:])

    def test_default_slot_does_not_modify_ds(self):
        modem = self.modem()
        self.assert_success(self.run_script(modem, "enable"))
        self.assertEqual(modem.values, {MAIN: "01", DS: "00"})
        self.assertFalse(any(DS in cmd and SET.fullmatch(cmd) for cmd in modem.commands))

    def test_already_enabled_flags_are_backed_up_without_set(self):
        originals = {MAIN: "01", DS: "01"}
        modem = self.modem(values=originals)
        self.assert_success(self.run_script(modem, "enable", ("--slot", "both")))
        self.assertEqual(modem.values, originals)
        self.assertFalse(any(SET.fullmatch(cmd) for cmd in modem.commands), modem.commands)
        backups = self.backups()
        self.assertEqual(len(backups), 1)
        for key in originals:
            self.assertIn(f"{key}\t0\t01\n", backups[0][1])

    def test_unsupported_get_never_writes(self):
        def intercept(modem, cmd):
            return b"\r\nERROR\r\n" if GET.fullmatch(cmd) else NotImplemented
        modem = self.modem(intercept=intercept)
        self.assert_failed_without_write(modem, self.run_script(modem, "enable"))

    def test_malformed_or_wrong_key_get_never_writes(self):
        replies = [
            f'+GOOGGETNV: "{MAIN}",0,"02"\r\nOK\r\n',
            f'+GOOGGETNV: "{DS}",0,"00"\r\nOK\r\n',
            f'+GOOGGETNV: "{MAIN}",1,"00"\r\nOK\r\n',
            f'+GOOGGETNV: "{MAIN}",0,"00"\r\n+GOOGGETNV: "{MAIN}",0,"00"\r\nOK\r\n',
            f'+GOOGGETNV: "{MAIN}",0,"00"\r\nERROR\r\n',
        ]
        for reply in replies:
            with self.subTest(reply=reply):
                modem = self.modem(intercept=lambda m, c, r=reply: r.encode() if GET.fullmatch(c) else NotImplemented)
                self.assert_failed_without_write(modem, self.run_script(modem, "enable"))

    def test_read_timeout_never_writes(self):
        modem = self.modem(intercept=lambda m, c: None if GET.fullmatch(c) else NotImplemented)
        self.assert_failed_without_write(modem, self.run_script(modem, "enable"))

    def test_zero_byte_idle_reads_and_fragmented_response_are_retried(self):
        fragmented = False

        def intercept(modem, command):
            nonlocal fragmented
            if command == f'AT+GOOGGETNV="{MAIN}"' and not fragmented:
                fragmented = True
                os.write(modem.master, f'\r\n+GOOGGETNV: "{MAIN}",0,"0'.encode())
                time.sleep(0.12)
                return b'0"\r\nOK\r\n'
            return NotImplemented

        modem = self.modem(intercept=intercept)
        attributes = termios.tcgetattr(modem.slave)
        attributes[6][termios.VMIN] = 0
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(modem.slave, termios.TCSANOW, attributes)
        self.assert_success(self.run_script(modem, "enable"))
        self.assertTrue(fragmented)
        self.assertEqual(modem.values[MAIN], "01")

    def test_second_set_error_rolls_back_touched_originals(self):
        failed = False

        def intercept(modem, command):
            nonlocal failed
            if command == f'AT+GOOGSETNV="{DS}",0,"01"' and not failed:
                failed = True
                modem.values[DS] = "01"  # An error does not prove the modem was unchanged.
                return b"\r\nERROR\r\n"
            return NotImplemented

        modem = self.modem(intercept=intercept)
        completed = self.run_script(modem, "enable", ("--slot", "both"))
        self.assertNotEqual(completed.returncode, 0)
        self.assertTrue(failed)
        self.assertEqual(modem.values, {MAIN: "00", DS: "00"}, modem.commands)
        for key in (MAIN, DS):
            self.assertIn(f'AT+GOOGSETNV="{key}",0,"00"', modem.commands)

    def test_readback_mismatch_rolls_back(self):
        enabled = False

        def intercept(modem, command):
            nonlocal enabled
            if command == f'AT+GOOGSETNV="{MAIN}",0,"01"':
                enabled = True
                return b"\r\nOK\r\n"  # Deliberately leave state unchanged.
            return NotImplemented

        modem = self.modem(intercept=intercept)
        completed = self.run_script(modem, "enable")
        self.assertTrue(enabled)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(modem.values[MAIN], "00")
        self.assertIn(f'AT+GOOGSETNV="{MAIN}",0,"00"', modem.commands)

    def test_set_timeout_after_apply_rolls_back_without_orphan_reader(self):
        timed_out_set = False

        def intercept(modem, command):
            nonlocal timed_out_set
            if command == f'AT+GOOGSETNV="{MAIN}",0,"01"' and not timed_out_set:
                timed_out_set = True
                modem.values[MAIN] = "01"
                return None  # The modem applied the write but never acknowledged.
            return NotImplemented

        modem = self.modem(intercept=intercept)
        completed = self.run_script(modem, "enable")
        self.assertTrue(timed_out_set)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(modem.values[MAIN], "00", modem.commands)
        self.assertIn(f"Rollback verified: {MAIN} index 0 = 00", completed.stdout)
        self.assertNotIn("ROLLBACK FAILED", completed.stderr)
        self.assertEqual(modem.commands[-2:], [f'AT+GOOGSETNV="{MAIN}",0,"00"',
                                              f'AT+GOOGGETNV="{MAIN}"'])

    def test_sigterm_during_applied_unacknowledged_set_rolls_back(self):
        applied = threading.Event()

        def intercept(modem, command):
            if command == f'AT+GOOGSETNV="{MAIN}",0,"01"' and not applied.is_set():
                modem.values[MAIN] = "01"
                applied.set()
                return None
            return NotImplemented

        modem = self.modem(intercept=intercept)
        process = subprocess.Popen(self.command(modem, "enable"), env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(applied.wait(3), "The first SET was not applied")
            # Target only the main shell. Its in-flight timeout worker must finish
            # before rollback starts, rather than steal subsequent restore replies.
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)
        if modem.errors:
            raise modem.errors[0]
        self.assertNotEqual(process.returncode, 0, stdout + stderr)
        self.assertEqual(modem.values[MAIN], "00", modem.commands)
        self.assertIn(f"Rollback verified: {MAIN} index 0 = 00", stdout)
        self.assertNotIn("ROLLBACK FAILED", stderr)
        self.assertEqual(modem.commands[-2:], [f'AT+GOOGSETNV="{MAIN}",0,"00"',
                                              f'AT+GOOGGETNV="{MAIN}"'])

    def test_explicit_restore_preserves_exact_backup_values(self):
        originals = {MAIN: "01", DS: "00"}
        modem = self.modem(values=originals)
        self.assert_success(self.run_script(modem, "enable", ("--slot", "both")))
        backup_dir = self.backups()[0][0].parent
        self.assertEqual(modem.values, {MAIN: "01", DS: "01"})
        self.assert_success(self.run_script(modem, "restore", (str(backup_dir),)))
        self.assertEqual(modem.values, originals)

    def test_malformed_restore_backup_is_rejected_without_write(self):
        bodies = [
            f"{MAIN}\t0\t00\n{DS}\t0\t01",  # Last row lacks the mandatory LF.
            f"{MAIN}\t0\t00\n{MAIN}\t0\t01\n",  # Duplicate key.
            "!UNRECOGNIZED.NV\t0\t00\n",
            f"{MAIN}\t1\t00\n",  # Only index zero is authorized.
            f"{MAIN}\t0\t00\tunexpected\n",  # Extra field.
        ]
        for index, body in enumerate(bodies):
            with self.subTest(body=body):
                backup_dir = self.root / f"invalid-restore-{index}"
                backup_dir.mkdir()
                (backup_dir / "backup.tsv").write_text("P9PF_NRDC_BACKUP_V1\n" + body)
                modem = self.modem()
                completed = self.run_script(modem, "restore", (str(backup_dir),))
                self.assert_failed_without_write(modem, completed)
                self.assertEqual(modem.commands, [], "Invalid backup must be rejected before port access")

    def test_shell_code_in_restore_backup_is_never_executed(self):
        marker = self.root / "must-not-be-created"
        backup_dir = self.root / "untrusted-restore"
        backup_dir.mkdir()
        (backup_dir / "backup.tsv").write_text(
            f"P9PF_NRDC_BACKUP_V1\n{MAIN}\t0\t$(touch {marker})\n"
        )
        modem = self.modem()
        completed = self.run_script(modem, "restore", (str(backup_dir),))
        self.assert_failed_without_write(modem, completed)
        self.assertFalse(marker.exists(), "Backup text must never be sourced or evaluated")
        self.assertEqual(modem.commands, [])

    def test_regular_port_is_refused_without_modification(self):
        port = self.root / "regular-file"
        port.write_bytes(b"original\n")
        modem = type("Port", (), {"port": str(port)})()
        completed = subprocess.run(self.command(modem, "enable"), env=self.env,
                                   capture_output=True, text=True, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(port.read_bytes(), b"original\n")
        port.unlink()
        completed = subprocess.run(self.command(modem, "enable"), env=self.env,
                                   capture_output=True, text=True, timeout=5)
        self.assertNotEqual(completed.returncode, 0)
        self.assertFalse(port.exists(), "Opening the port must not create a regular file")

    def test_concurrent_run_is_refused_before_port_transaction(self):
        release = threading.Event()

        def intercept(modem, command):
            if len(modem.commands) == 1:
                release.wait(3)
            return NotImplemented

        modem = self.modem(intercept=intercept)
        first = subprocess.Popen(self.command(modem), env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(modem.first_command.wait(2), "First audit did not begin")
            second = subprocess.run(self.command(modem), env=self.env,
                                    capture_output=True, text=True, timeout=3)
            self.assertNotEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(len(modem.commands), 1, "Second process must not access the port")
        finally:
            release.set()
            first.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
