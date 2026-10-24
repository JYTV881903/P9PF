#!/system/bin/sh
# Generated from android/NrSaPolicy.java by tools/build_sa_oneclick.py.
# Source: https://github.com/JYTV881903/P9PF
# Root Pixel 9 Pro Fold / Android 16 only. Default operation: temporary SA enable.
# Embedded DEX JAR SHA-256: 14dbebf137ad7a7583e22cb5fe0ad3ebd4aa990a15a2a13631bed66a0f19d348
# Java source SHA-256: f2a5992fe1f9ead1d04e1a926dd09b7408d212c0d8d76a1fc589416565c222ca
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
EXPECTED=14dbebf137ad7a7583e22cb5fe0ad3ebd4aa990a15a2a13631bed66a0f19d348
STAGED=$CACHE/nr-sa-policy-$EXPECTED.jar
if [ ! -e "$STAGED" ]; then
    CANDIDATE=$CACHE/oneclick-$$.jar
    [ ! -e "$CANDIDATE" ] || exit 1
    TEMP=$CANDIDATE
    base64 -d >"$TEMP" <<'P9PF_DEX_PAYLOAD'
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
cy5kZXhQSwUGAAAAAAEAAQA5AAAAqSsAAAAA
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
