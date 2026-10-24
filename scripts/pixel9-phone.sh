#!/system/bin/sh
# Phone-only entry point. Requires an existing root terminal; never escalates
# privileges or enables flags automatically after an audit.

if [ -x /system/bin/sh ]; then
    SHELL_BIN=/system/bin/sh
    PATH=/system/bin:/system/xbin:/vendor/bin
    export PATH
else
    # Host tests use isolated stub child scripts; this is not an Android claim.
    SHELL_BIN=$(command -v sh)
fi

usage() {
    cat <<'EOF'
Usage: sh pixel9-phone.sh [audit|enable-both|restore BACKUPDIR]
  audit         Read-only NV and CarrierConfig report (default).
  enable-both   Back up, enable both existing NRDC flags, and verify.
  restore DIR   Restore the exact flags from DIR/backup.tsv.
Run from a root terminal (type su first). No computer or ADB is used.
EOF
}

MODE=${1-audit}
RESTORE_DIR=
case $MODE in
    audit|enable-both) [ "$#" -le 1 ] || { usage >&2; exit 64; } ;;
    restore) [ "$#" -eq 2 ] || { usage >&2; exit 64; }; RESTORE_DIR=$2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 64 ;;
esac

[ "$(id -u)" = 0 ] || { echo 'Type su in your phone terminal first, then run this command again.' >&2; exit 1; }
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
CORE=$SCRIPT_DIR/pixel9-csl-nrdc.sh
CARRIER=$SCRIPT_DIR/../tools/audit_nr_carrier_config.sh
[ -r "$CORE" ] && [ -r "$CARRIER" ] || { echo 'Keep the extracted scripts/ and tools/ folders together.' >&2; exit 1; }

# Optional path overrides also let host tests use a fully isolated fixture.
STATE_ROOT=${P9PF_STATE_ROOT:-/data/local/tmp/p9pf-nrdc}
DOWNLOAD_DIR=${P9PF_DOWNLOAD_DIR:-/sdcard/Download}
case $STATE_ROOT in /*) ;; *) echo 'State root must be an absolute path.' >&2; exit 1 ;; esac
case $DOWNLOAD_DIR in /*) ;; *) echo 'Download directory must be an absolute path.' >&2; exit 1 ;; esac
umask 077
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
REPORT_DIR=$STATE_ROOT/phone-$STAMP-$$
mkdir -p "$STATE_ROOT" && mkdir "$REPORT_DIR" || exit 1
echo "Phone report directory: $REPORT_DIR"

case $MODE in
    audit)
        "$SHELL_BIN" "$CORE" audit --slot both --state-root "$STATE_ROOT" >"$REPORT_DIR/nv-console.txt" 2>&1 ;;
    enable-both)
        "$SHELL_BIN" "$CORE" enable --slot both --state-root "$STATE_ROOT" >"$REPORT_DIR/nv-console.txt" 2>&1 ;;
    restore)
        "$SHELL_BIN" "$CORE" restore "$RESTORE_DIR" --state-root "$STATE_ROOT" >"$REPORT_DIR/nv-console.txt" 2>&1 ;;
esac
NV_STATUS=$?
cat "$REPORT_DIR/nv-console.txt"

"$SHELL_BIN" "$CARRIER" >"$REPORT_DIR/carrier-console.txt" 2>&1
CARRIER_STATUS=$?
cat "$REPORT_DIR/carrier-console.txt"

PRIVATE_REPORT=$REPORT_DIR/report.txt
{
    printf 'P9PF phone-only NRDC report\nmode=%s\nNV_exit_code=%s\nCarrierConfig_exit_code=%s\n' "$MODE" "$NV_STATUS" "$CARRIER_STATUS"
    if command -v getprop >/dev/null 2>&1; then
        for _prop in ro.product.model ro.product.device ro.build.version.release ro.build.id gsm.version.baseband; do
            printf '%s=%s\n' "$_prop" "$(getprop "$_prop")"
        done
    fi
    printf '\nNV command summary (not raw AT transcripts):\n'
    cat "$REPORT_DIR/nv-console.txt"
    printf '\nFiltered CarrierConfig (not the full dump):\n'
    cat "$REPORT_DIR/carrier-console.txt"
    printf '\nThis report does not establish an active CSL NRDC connection.\n'
} >"$PRIVATE_REPORT" || exit 1

PUBLIC_REPORT=$DOWNLOAD_DIR/P9PF-NRDC-report-$STAMP-$$.txt
EXPORT_STATUS=0
if [ -d "$DOWNLOAD_DIR" ] && (set -C; cat "$PRIVATE_REPORT" >"$PUBLIC_REPORT"); then
    echo "Share this report: $PUBLIC_REPORT"
else
    echo "Report export failed; private report preserved at: $PRIVATE_REPORT" >&2
    EXPORT_STATUS=1
fi
# Keep backup.tsv, touched.tsv, reply-*.txt and full dumps out of the public file.
[ "$NV_STATUS" -eq 0 ] || exit "$NV_STATUS"
[ "$CARRIER_STATUS" -eq 0 ] || exit "$CARRIER_STATUS"
exit "$EXPORT_STATUS"
