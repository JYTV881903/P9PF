#!/usr/bin/env python3
"""Generate a single phone shell file containing the verified DEX helper."""
import base64
import hashlib
import json
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]
JAR = ROOT / "android" / "nr-sa-policy.jar"

TEMPLATE = r'''#!/system/bin/sh
# Generated from android/NrSaPolicy.java by tools/build_sa_oneclick.py.
# Source: https://github.com/JYTV881903/P9PF
# Root Pixel 9 Pro Fold / Android 16 only. Default operation: temporary SA enable.
# Embedded DEX JAR SHA-256: @HASH@
# Java source SHA-256: @SOURCE_HASH@
# No NV writes, permanent CarrierConfig override, boot job or automatic reboot.

MODE=${1:-enable}
BACKUP=
case $MODE in
    enable|status) [ "$#" -le 1 ] || exit 64 ;;
    restore) [ "$#" -eq 2 ] || { echo 'Usage: sh pixel9-csl-sa-oneclick.sh restore FULL_BACKUP_FILE'; exit 64; }; BACKUP=$2 ;;
    -h|--help)
        echo 'Root phone: sh pixel9-csl-sa-oneclick.sh [enable|status|restore FULL_BACKUP_FILE]'
        echo 'Default: temporarily change data SIM policy [1] to [1,2], with saved baseline and readback.'
        echo 'A normal reboot removes this temporary test. Configuration success does not prove NRDC.'
        exit 0 ;;
    *) echo 'Unknown operation.' >&2; exit 64 ;;
esac
PATH=/system/bin:/system/xbin:/vendor/bin
export PATH
[ "$(id -u)" = 0 ] || { echo 'Open a root terminal with su first.' >&2; exit 1; }
[ "$(getprop ro.product.device)" = comet ] && [ "$(getprop ro.build.version.sdk)" = 36 ] || {
    echo 'This test is limited to Pixel 9 Pro Fold (comet), Android 16/API 36. No change attempted.' >&2
    exit 1
}
[ -x /system/bin/app_process ] || { echo 'Android app_process unavailable.' >&2; exit 1; }
for TOOL in base64 sha256sum mkdir chmod mv cat rm rmdir timeout grep date; do
    command -v "$TOOL" >/dev/null 2>&1 || { echo "Missing system utility: $TOOL" >&2; exit 1; }
done

umask 077
STATE=/data/local/tmp/p9pf-nrdc
CACHE=$STATE/sa-runtime
mkdir -p "$CACHE" || exit 1
LOCK=$CACHE/operation.lock
mkdir "$LOCK" 2>/dev/null || { echo 'An SA test or its lock already exists; no change attempted.' >&2; exit 1; }
TEMP=
cleanup() {
    [ -z "$TEMP" ] || rm -f "$TEMP"
    if [ "$(cat "$LOCK/owner.pid" 2>/dev/null)" = "$$" ]; then
        rm -f "$LOCK/owner.pid"
        rmdir "$LOCK" 2>/dev/null || :
    elif [ ! -e "$LOCK/owner.pid" ]; then
        rmdir "$LOCK" 2>/dev/null || :
    fi
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
printf '%s\n' "$$" >"$LOCK/owner.pid" || exit 1
EXPECTED=@HASH@
STAGED=$CACHE/nr-sa-policy-$EXPECTED.jar
if [ ! -e "$STAGED" ]; then
    CANDIDATE=$CACHE/oneclick-$$.jar
    [ ! -e "$CANDIDATE" ] || exit 1
    TEMP=$CANDIDATE
    base64 -d >"$TEMP" <<'P9PF_DEX_PAYLOAD'
@PAYLOAD@
P9PF_DEX_PAYLOAD
    DECODE_STATUS=$?
    [ "$DECODE_STATUS" -eq 0 ] || { echo 'Embedded helper decode failed.' >&2; exit 1; }
    COPIED=$(sha256sum "$TEMP") || exit 1
    [ "${COPIED%% *}" = "$EXPECTED" ] || { echo 'Embedded helper checksum mismatch.' >&2; exit 1; }
    chmod 444 "$TEMP" && mv "$TEMP" "$STAGED" || exit 1
    TEMP=
fi
chmod 444 "$STAGED" || exit 1
FINAL=$(sha256sum "$STAGED") || exit 1
[ "${FINAL%% *}" = "$EXPECTED" ] || { echo 'Staged helper checksum mismatch; no change attempted.' >&2; exit 1; }

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RUN=$STATE/phone-SA-$STAMP-$$
mkdir "$RUN" || exit 1
echo 'Checking the live data SIM and its SA policy...'
CLASSPATH=$STAGED
export CLASSPATH
case $MODE in
    enable|status)
        timeout -s 9 40 /system/bin/app_process /system/bin dev.p9pf.nrdc.NrSaPolicy "$MODE" --state-root "$STATE/sa-policy" >"$RUN/policy.txt" 2>&1 ;;
    restore)
        timeout -s 9 40 /system/bin/app_process /system/bin dev.p9pf.nrdc.NrSaPolicy restore "$BACKUP" --state-root "$STATE/sa-policy" >"$RUN/policy.txt" 2>&1 ;;
esac
POLICY_STATUS=$?
cat "$RUN/policy.txt"
# Filter before saving; never export the full carrier_config dump.
(
    set -o pipefail
    timeout -s 9 10 dumpsys carrier_config | grep -E '^[[:space:]]*(Phone Id = [0-9]+[[:space:]]*$|Default Values from CarrierConfigManager[[:space:]]*:|mConfigFrom(DefaultApp|CarrierApp)[[:space:]]*:|m(PersistentOverrideConfigs|OverrideConfigs|NoSimConfig)[[:space:]]*:|carrier_nr_availabilities_int_array[[:space:]]*=|Permission Denial:)'
) >"$RUN/carrier.txt" 2>&1
CARRIER_STATUS=$?
cat "$RUN/carrier.txt"
{
    printf 'P9PF temporary SA policy report\nmode=%s\nSA_policy_exit_code=%s\nCarrierConfig_exit_code=%s\n' "$MODE" "$POLICY_STATUS" "$CARRIER_STATUS"
    cat "$RUN/policy.txt"
    printf '\nFiltered CarrierConfig:\n'
    cat "$RUN/carrier.txt"
    printf '\nThis report does not prove an active CSL NRDC connection.\n'
} >"$RUN/report.txt" || exit 1
PUBLIC=/sdcard/Download/P9PF-SA-report-$STAMP-$$.txt
EXPORT_STATUS=0
if [ -d /sdcard/Download ] && (set -C; cat "$RUN/report.txt" >"$PUBLIC"); then
    echo "Share this report: $PUBLIC"
else
    echo "Download export failed. Private report preserved: $RUN/report.txt" >&2
    EXPORT_STATUS=1
fi
echo 'This test is temporary. Test the connection before reboot; a normal reboot removes this override.'
[ "$POLICY_STATUS" -eq 0 ] || exit "$POLICY_STATUS"
[ "$CARRIER_STATUS" -eq 0 ] || exit "$CARRIER_STATUS"
exit "$EXPORT_STATUS"
'''


def generate():
    data = JAR.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    fields = (ROOT / "android" / "nr-sa-policy.sha256").read_text().split()
    if fields != [digest, JAR.name]:
        raise SystemExit("Build artifact/manifest mismatch; refusing generation.")
    metadata = json.loads((ROOT / "android" / "nr-sa-policy.build.json").read_text())
    source_hash = hashlib.sha256((ROOT / "android" / "NrSaPolicy.java").read_bytes()).hexdigest()
    if metadata.get("source_sha256") != source_hash or metadata.get("jar_sha256") != digest:
        raise SystemExit("Java source/build metadata mismatch; rebuild before generation.")
    payload = "\n".join(textwrap.wrap(base64.b64encode(data).decode("ascii"), 76))
    source = TEMPLATE.replace("@HASH@", digest).replace("@SOURCE_HASH@", source_hash).replace("@PAYLOAD@", payload)
    destination = ROOT / "scripts" / "pixel9-csl-sa-oneclick.sh"
    destination.write_text(source, encoding="utf-8")
    print(f"Generated {destination.name}: {destination.stat().st_size} bytes")


if __name__ == "__main__":
    generate()
