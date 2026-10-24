#!/usr/bin/env python3
"""Build the phone's reflection-only app_process helper from its Java source.

Requires Java with the jdk.compiler module and Python 3. The phone uses the
committed DEX JAR directly and does not need build tools.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

R8_VERSION = "8.9.35"
R8_SHA256 = "204b2fc2b0f4e888dc0ef748b58090def1bf4185068d36abbb94841dbc7107a8"
R8_URL = f"https://dl.google.com/dl/android/maven2/com/android/tools/r8/{R8_VERSION}/r8-{R8_VERSION}.jar"


def build(cache):
    root = Path(__file__).resolve().parents[1]
    java = shutil.which("java")
    if java is None:
        raise SystemExit("Java with jdk.compiler is required.")
    cache.mkdir(parents=True, exist_ok=True)
    compiler = cache / f"r8-{R8_VERSION}.jar"
    if not compiler.exists():
        with urllib.request.urlopen(R8_URL, timeout=90) as response:
            data = response.read(100 * 1024 * 1024 + 1)
        if hashlib.sha256(data).hexdigest() != R8_SHA256:
            raise SystemExit("Official R8 artifact checksum mismatch; refusing execution.")
        compiler.write_bytes(data)
    if hashlib.sha256(compiler.read_bytes()).hexdigest() != R8_SHA256:
        raise SystemExit("Cached R8 artifact checksum mismatch; refusing execution.")
    with tempfile.TemporaryDirectory(prefix="p9pf-sa-build-") as temporary:
        directory = Path(temporary)
        classes = directory / "classes"
        dex = directory / "dex"
        classes.mkdir()
        dex.mkdir()
        # Source uses only Java APIs present on Android 26+. This host's compiler
        # module may ship without the historical ct.sym needed by --release 8.
        subprocess.run([java, "com.sun.tools.javac.Main", "-source", "8", "-target", "8", "-encoding", "UTF-8",
                        "-d", str(classes), str(root / "android" / "NrSaPolicy.java")], check=True)
        inputs = sorted(str(p) for p in classes.rglob("*.class"))
        if not inputs:
            raise SystemExit("Compilation produced no classes; keeping the previous helper.")
        subprocess.run([java, "-cp", str(compiler), "com.android.tools.r8.D8", "--release",
                        "--min-api", "26", "--output", str(dex), *inputs], check=True)
        outputs = sorted(dex.glob("*.dex"))
        if not outputs or not (dex / "classes.dex").is_file():
            raise SystemExit("D8 produced no classes.dex; keeping the previous helper.")
        for path in outputs:
            if path.stat().st_size < 112 or not path.read_bytes().startswith(b"dex\n"):
                raise SystemExit("D8 output is not a DEX file; keeping the previous helper.")
        target = root / "android" / "nr-sa-policy.jar"
        pending = directory / "nr-sa-policy.jar"
        with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in outputs:
                entry = zipfile.ZipInfo(path.name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, path.read_bytes())
        digest = hashlib.sha256(pending.read_bytes()).hexdigest()
        manifest = directory / "nr-sa-policy.sha256"
        manifest.write_text(digest + "  nr-sa-policy.jar\n")
        source = root / "android" / "NrSaPolicy.java"
        metadata = {
            "source": "android/NrSaPolicy.java",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "jar_sha256": digest,
            "classfile_target": 8,
            "min_android_api": 26,
            "r8_version": R8_VERSION,
            "r8_sha256": R8_SHA256,
        }
        # Copy to adjacent temporary files before atomic replacement; a failed
        # compiler cannot truncate the last working artifact. A manifest/JAR
        # mismatch after interrupted replacement fails closed in the launcher.
        adjacent = target.with_suffix(".jar.tmp")
        adjacent_manifest = root / "android" / "nr-sa-policy.sha256.tmp"
        adjacent_metadata = root / "android" / "nr-sa-policy.build.json.tmp"
        shutil.copyfile(pending, adjacent)
        shutil.copyfile(manifest, adjacent_manifest)
        adjacent_metadata.write_text(json.dumps(metadata, sort_keys=True, indent=2) + "\n")
        adjacent.replace(target)
        adjacent_manifest.replace(root / "android" / "nr-sa-policy.sha256")
        adjacent_metadata.replace(root / "android" / "nr-sa-policy.build.json")
        print(f"Built {target.name}: {target.stat().st_size} bytes; SHA-256 {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path,
                        default=Path(tempfile.gettempdir()) / "p9pf-sa-build-tools")
    build(parser.parse_args().cache)
