"""Check the standalone phone script without running Android or root commands."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "android" / "nr-sa-policy.jar"
MANIFEST = ROOT / "android" / "nr-sa-policy.sha256"
ONECLICK = ROOT / "scripts" / "pixel9-csl-sa-oneclick.sh"
GENERATOR = ROOT / "tools" / "build_sa_oneclick.py"
JAVA_SOURCE = ROOT / "android" / "NrSaPolicy.java"
BUILD_METADATA = ROOT / "android" / "nr-sa-policy.build.json"


def dex_class_descriptors(data: bytes) -> list[str]:
    """Read class_def -> type_id -> string_id, not incidental DEX strings."""
    if len(data) < 112 or not re.fullmatch(rb"dex\n[0-9]{3}\x00", data[:8]):
        raise ValueError("Not a complete standard DEX file")
    if struct.unpack_from("<I", data, 32)[0] != len(data):
        raise ValueError("DEX file size mismatch")
    if struct.unpack_from("<I", data, 36)[0] != 112:
        raise ValueError("Unsupported DEX header size")
    if struct.unpack_from("<I", data, 40)[0] != 0x12345678:
        raise ValueError("Unsupported DEX endian tag")
    if hashlib.sha1(data[32:]).digest() != data[12:32]:
        raise ValueError("DEX signature mismatch")
    if zlib.adler32(data[12:]) & 0xFFFFFFFF != struct.unpack_from("<I", data, 8)[0]:
        raise ValueError("DEX checksum mismatch")

    def table(header_offset: int, entry_size: int) -> tuple[int, int]:
        count, offset = struct.unpack_from("<II", data, header_offset)
        if offset > len(data) or count > (len(data) - offset) // entry_size:
            raise ValueError("DEX table outside file")
        return count, offset

    string_count, strings = table(56, 4)
    type_count, types = table(64, 4)
    class_count, classes = table(96, 32)
    descriptors = []
    for class_number in range(class_count):
        type_index = struct.unpack_from("<I", data, classes + class_number * 32)[0]
        if type_index >= type_count:
            raise ValueError("Class type index outside table")
        string_index = struct.unpack_from("<I", data, types + type_index * 4)[0]
        if string_index >= string_count:
            raise ValueError("Type string index outside table")
        offset = struct.unpack_from("<I", data, strings + string_index * 4)[0]
        # string_data_item starts with a ULEB128 UTF-16 length. Class descriptors
        # in this helper are ASCII; unrelated strings are deliberately not read.
        for _ in range(5):
            if offset >= len(data):
                raise ValueError("String length outside file")
            byte = data[offset]
            offset += 1
            if byte < 0x80:
                break
        else:
            raise ValueError("Invalid string length")
        try:
            end = data.index(0, offset)
        except ValueError as exc:
            raise ValueError("Unterminated class descriptor") from exc
        descriptors.append(data[offset:end].decode("ascii"))
    return descriptors


class SaPackagingTests(unittest.TestCase):
    def test_standalone_shell_syntax_without_execution(self):
        shell = shutil.which("dash") or "/bin/sh"
        checked = subprocess.run([shell, "-n", str(ONECLICK)], capture_output=True,
                                 text=True, timeout=5)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_embedded_payload_matches_jar_manifest_and_header(self):
        script = ONECLICK.read_text()
        payload = re.search(
            r"<<'P9PF_DEX_PAYLOAD'\n([A-Za-z0-9+/=\n]+)\nP9PF_DEX_PAYLOAD\n",
            script,
        )
        self.assertIsNotNone(payload, "Standalone script needs its complete embedded helper")
        decoded = base64.b64decode("".join(payload.group(1).splitlines()), validate=True)
        self.assertEqual(decoded, JAR.read_bytes())
        digest = hashlib.sha256(decoded).hexdigest()
        self.assertEqual(MANIFEST.read_text().split(), [digest, JAR.name])
        self.assertEqual(re.findall(r"^# Embedded DEX JAR SHA-256: ([0-9a-f]{64})$",
                                    script, re.MULTILINE), [digest])
        self.assertEqual(re.findall(r"^EXPECTED=([0-9a-f]{64})$", script, re.MULTILINE),
                         [digest])
        self.assertNotIn("@HASH@", script)
        self.assertNotIn("@PAYLOAD@", script)

    def test_jar_defines_only_helper_namespace_classes(self):
        with zipfile.ZipFile(JAR) as archive:
            self.assertIsNone(archive.testzip(), "JAR CRC validation")
            self.assertFalse(any(name.endswith(".class") for name in archive.namelist()),
                             "Phone artifact must be DEX, not JVM class files")
            dex_names = [name for name in archive.namelist() if name.endswith(".dex")]
            self.assertEqual(dex_names, ["classes.dex"])
            descriptors = dex_class_descriptors(archive.read("classes.dex"))
        self.assertTrue(descriptors, "A DEX with zero classes cannot run the helper")
        self.assertIn("Ldev/p9pf/nrdc/NrSaPolicy;", descriptors)
        unexpected = [name for name in descriptors
                      if not (name.startswith("Ldev/p9pf/nrdc/") and name.endswith(";"))]
        self.assertEqual(unexpected, [], "No platform, runtime, or unrelated class definitions")

    def test_provenance_matches_source_artifact_compiler_pin_and_script_header(self):
        metadata = json.loads(BUILD_METADATA.read_text())
        source_hash = hashlib.sha256(JAVA_SOURCE.read_bytes()).hexdigest()
        self.assertEqual(metadata["source"], "android/NrSaPolicy.java")
        self.assertEqual(metadata["source_sha256"], source_hash)
        self.assertEqual(metadata["jar_sha256"], hashlib.sha256(JAR.read_bytes()).hexdigest())
        self.assertEqual(metadata["r8_version"], "8.9.35")
        self.assertEqual(metadata["r8_sha256"],
                         "204b2fc2b0f4e888dc0ef748b58090def1bf4185068d36abbb94841dbc7107a8")
        self.assertEqual(metadata["classfile_target"], 8)
        self.assertEqual(metadata["min_android_api"], 26)
        self.assertEqual(re.findall(r"^# Java source SHA-256: ([0-9a-f]{64})$",
                                    ONECLICK.read_text(), re.MULTILINE), [source_hash])

    def test_generation_is_reproducible_without_modifying_checkout(self):
        spec = importlib.util.spec_from_file_location("p9pf_packaging_fixture", GENERATOR)
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory(prefix="p9pf-packaging-test-") as directory:
            root = Path(directory)
            (root / "android").mkdir()
            (root / "scripts").mkdir()
            copied_jar = root / "android" / JAR.name
            shutil.copyfile(JAR, copied_jar)
            shutil.copyfile(MANIFEST, root / "android" / MANIFEST.name)
            shutil.copyfile(JAVA_SOURCE, root / "android" / JAVA_SOURCE.name)
            shutil.copyfile(BUILD_METADATA, root / "android" / BUILD_METADATA.name)
            generator.ROOT = root
            generator.JAR = copied_jar
            generator.generate()
            self.assertEqual((root / "scripts" / ONECLICK.name).read_bytes(),
                             ONECLICK.read_bytes())
            # A changed checksum must stop packaging rather than produce an
            # internally consistent-looking script from an unverified input.
            (root / "android" / MANIFEST.name).write_text("0" * 64 + "  " + JAR.name + "\n")
            (root / "scripts" / ONECLICK.name).unlink()
            with self.assertRaises(SystemExit):
                generator.generate()
            self.assertFalse((root / "scripts" / ONECLICK.name).exists())
            # A current JAR checksum cannot excuse stale Java build provenance.
            shutil.copyfile(MANIFEST, root / "android" / MANIFEST.name)
            with (root / "android" / JAVA_SOURCE.name).open("a") as stream:
                stream.write("\n// Changed since the packaged build.\n")
            with self.assertRaises(SystemExit):
                generator.generate()
            self.assertFalse((root / "scripts" / ONECLICK.name).exists())

    def test_oneclick_defaults_to_enable_and_contains_no_nv_transport(self):
        script = ONECLICK.read_text()
        self.assertIn("MODE=${1:-enable}", script)
        self.assertIn("dev.p9pf.nrdc.NrSaPolicy", script)
        self.assertNotIn("GOOGSETNV", script)
        self.assertNotIn("/dev/umts_router", script)
        self.assertNotIn("pixel9-csl-nrdc.sh", script)


if __name__ == "__main__":
    unittest.main()
