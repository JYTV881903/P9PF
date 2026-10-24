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
Usage: sh pixel9-phone.sh [audit|enable-both|restore BACKUPDIR|sa-status|sa-enable|sa-restore BACKUPFILE]
  audit         Read-only NV and CarrierConfig report (default).
  enable-both   Back up, enable both existing NRDC flags, and verify.
  restore DIR   Restore the exact flags from DIR/backup.tsv.
  sa-status     Read the data SIM's effective SA policy and subscription mapping.
  sa-enable     Temporarily allow SA+NSA on the data SIM when its policy is [1].
  sa-restore F  Restore the effective policy value saved in backup file F.
Run from a root terminal (type su first). No computer or ADB is used.
EOF
}

MODE=${1-audit}
RESTORE_DIR=
case $MODE in
    audit|enable-both|sa-status|sa-enable) [ "$#" -le 1 ] || { usage >&2; exit 64; } ;;
    restore|sa-restore) [ "$#" -eq 2 ] || { usage >&2; exit 64; }; RESTORE_DIR=$2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 64 ;;
esac

[ "$(id -u)" = 0 ] || { echo 'Type su in your phone terminal first, then run this command again.' >&2; exit 1; }
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
CORE=$SCRIPT_DIR/pixel9-csl-nrdc.sh
CARRIER=$SCRIPT_DIR/../tools/audit_nr_carrier_config.sh
SA=$SCRIPT_DIR/pixel9-sa.sh
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
OPERATION=NV
CONSOLE=$REPORT_DIR/nv-console.txt
case $MODE in
    sa-*)
        [ -r "$SA" ] || { echo 'Updated phone package is incomplete: pixel9-sa.sh missing.' >&2; exit 1; }
        OPERATION=SA_policy
        CONSOLE=$REPORT_DIR/sa-console.txt ;;
esac

case $MODE in
    audit)
        "$SHELL_BIN" "$CORE" audit --slot both --state-root "$STATE_ROOT" >"$CONSOLE" 2>&1 ;;
    enable-both)
        "$SHELL_BIN" "$CORE" enable --slot both --state-root "$STATE_ROOT" >"$CONSOLE" 2>&1 ;;
    restore)
        "$SHELL_BIN" "$CORE" restore "$RESTORE_DIR" --state-root "$STATE_ROOT" >"$CONSOLE" 2>&1 ;;
    sa-status)
        "$SHELL_BIN" "$SA" status --state-root "$STATE_ROOT/sa-policy" >"$CONSOLE" 2>&1 ;;
    sa-enable)
        "$SHELL_BIN" "$SA" enable --state-root "$STATE_ROOT/sa-policy" >"$CONSOLE" 2>&1 ;;
    sa-restore)
        "$SHELL_BIN" "$SA" restore "$RESTORE_DIR" --state-root "$STATE_ROOT/sa-policy" >"$CONSOLE" 2>&1 ;;
esac
OPERATION_STATUS=$?
cat "$CONSOLE"

"$SHELL_BIN" "$CARRIER" >"$REPORT_DIR/carrier-console.txt" 2>&1
CARRIER_STATUS=$?
cat "$REPORT_DIR/carrier-console.txt"

PRIVATE_REPORT=$REPORT_DIR/report.txt
{
    printf 'P9PF phone-only NRDC report\nmode=%s\n%s_exit_code=%s\nCarrierConfig_exit_code=%s\n' "$MODE" "$OPERATION" "$OPERATION_STATUS" "$CARRIER_STATUS"
    if command -v getprop >/dev/null 2>&1; then
        for _prop in ro.product.model ro.product.device ro.build.version.release ro.build.id gsm.version.baseband; do
            printf '%s=%s\n' "$_prop" "$(getprop "$_prop")"
        done
    fi
    printf '\n%s command summary:\n' "$OPERATION"
    cat "$CONSOLE"
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
[ "$OPERATION_STATUS" -eq 0 ] || exit "$OPERATION_STATUS"
[ "$CARRIER_STATUS" -eq 0 ] || exit "$CARRIER_STATUS"
exit "$EXPORT_STATUS"
