#!/system/bin/sh
# Targeted NRDC experiment, not a band-combination or modem firmware patch.
# Default is read-only audit. Writes are limited to the two flags already in
# the supplied script, with exact-value backup, readback and rollback.

_exchange() {
    _port=$1
    _command=$2
    [ -c "$_port" ] && [ -r "$_port" ] && [ -w "$_port" ] || return 70
    exec 3<>"$_port" || return 71
    printf '%s\r' "$_command" >&3 || return 72
    _partial=
    _cr=$(printf '\r')
    while :; do
        _line=
        IFS= read -r _line <&3
        _read_status=$?
        _partial=$_partial$_line
        if [ "$_read_status" -ne 0 ]; then
            # This driver's zero-byte idle read is not a completed response.
            # Process a CR-terminated fragment; otherwise retain partial data.
            case $_partial in
                *"$_cr") ;;
                *) sleep 0.05; continue ;;
            esac
        fi
        _line=$_partial
        _partial=
        while :; do
            case $_line in *"$_cr") _line=${_line%"$_cr"} ;; *) break ;; esac
        done
        [ -n "$_line" ] || continue
        printf '%s\n' "$_line"
        case $_line in
            OK) return 0 ;;
            ERROR|'+CME ERROR:'*|'+CMS ERROR:'*) return 73 ;;
        esac
    done
}

# Internal transport worker, always invoked under external timeout.
if [ "${1-}" = _exchange ]; then
    [ "$#" -eq 3 ] || exit 64
    _exchange "$2" "$3"
    exit $?
fi

MAIN_KEY='!NRCOMMON.NrDcSupport'
DS_KEY='!NRCOMMON.NrDcSupport_DS'
MODE=audit
SLOT=main
PORT=/dev/umts_router
STATE_ROOT=/data/local/tmp/p9pf-nrdc
TIMEOUT=5
RESTORE_DIR=
LOCK_OWNED=0
RUN_DIR=
MUTATION_STARTED=0
COMPLETED=0
ROLLBACK_RUNNING=0
SEQ=0
TAB=$(printf '\t')

usage() {
    cat <<'EOF'
Usage: pixel9-csl-nrdc.sh [audit|enable|restore BACKUPDIR] [options]
  audit                   Read-only NV audit (default).
  enable                  Back up, enable selected existing NRDC flag(s), verify.
  restore BACKUPDIR       Restore only the validated original flags in backup.tsv.
  --slot main|ds|both      Existing key scope for audit/enable (default main).
  --port DEVICE           Character device (default /dev/umts_router).
  --state-root DIR        Private logs/backups/lock (default /data/local/tmp/p9pf-nrdc).
  --timeout SECONDS       Per-exchange deadline, integer 1..30 (default 5).
No radio restart/reboot or band/power/profile edits are performed.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }

if [ "$#" -gt 0 ]; then
    case $1 in
        audit|enable) MODE=$1; shift ;;
        restore)
            MODE=restore; shift
            [ "$#" -gt 0 ] || { usage >&2; exit 64; }
            RESTORE_DIR=$1; shift ;;
        -h|--help) usage; exit 0 ;;
        --*) ;;
        *) usage >&2; exit 64 ;;
    esac
fi
while [ "$#" -gt 0 ]; do
    case $1 in
        --slot|--port|--state-root|--timeout)
            [ "$#" -ge 2 ] || die "Missing value for $1"
            case $1 in
                --slot) SLOT=$2 ;;
                --port) PORT=$2 ;;
                --state-root) STATE_ROOT=$2 ;;
                --timeout) TIMEOUT=$2 ;;
            esac
            shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done
case $SLOT in main|ds|both) ;; *) die 'Invalid --slot' ;; esac
case $TIMEOUT in ''|*[!0-9]*) die 'Timeout must be an integer 1..30' ;; esac
[ "$TIMEOUT" -ge 1 ] && [ "$TIMEOUT" -le 30 ] || die 'Timeout must be 1..30'
case $PORT in /*) ;; *) die 'Port must be an absolute character-device path' ;; esac
case $STATE_ROOT in /*) ;; *) die 'State root must be an absolute directory path' ;; esac
[ "$(id -u)" = 0 ] || die 'Root is required; no modem command was sent'
[ -c "$PORT" ] && [ -r "$PORT" ] && [ -w "$PORT" ] || die 'Port must be a readable/writable character device'
for _tool in timeout sed date mkdir mv sync sleep tail cat rm rmdir; do
    command -v "$_tool" >/dev/null 2>&1 || die "Required utility missing: $_tool"
done
if [ -x /system/bin/sh ]; then SHELL_BIN=/system/bin/sh; else SHELL_BIN=$(command -v sh); fi
case $0 in /*) SELF=$0 ;; *) SELF=$(pwd)/$0 ;; esac
[ -r "$SELF" ] || die 'Cannot locate the script for the timed transport worker'
umask 077
mkdir -p "$STATE_ROOT" || die 'Cannot create state root'
LOCK_DIR=$STATE_ROOT/lock

exchange() {
    _cmd=$1
    SEQ=$((SEQ + 1))
    REPLY=$RUN_DIR/reply-$SEQ.txt
    # KILL is directed only at this timeout-managed worker, ensuring it cannot
    # survive the deadline and consume a later transaction's response.
    timeout -s 9 "$TIMEOUT" "$SHELL_BIN" "$SELF" _exchange "$PORT" "$_cmd" >"$REPLY" 2>"$RUN_DIR/transport-$SEQ.err"
    _status=$?
    [ "$_status" -eq 0 ] || return "$_status"
    # Worker success requires a terminal OK, and verify the persisted transcript.
    [ "$(tail -n 1 "$REPLY")" = OK ] || return 74
    return 0
}

parse_nv_row() {
    # Strip only whitespace OUTSIDE quoted values. Names/values remain exact.
    _parsed=$(printf '%s\n' "$1" | sed -n 's/^[[:blank:]]*+GOOGGETNV:[[:blank:]]*"\([^"[:cntrl:]]*\)"[[:blank:]]*,[[:blank:]]*\([0-9][0-9]*\)[[:blank:]]*,[[:blank:]]*"\([^"[:cntrl:]]*\)"[[:blank:]]*$/\1'"$TAB"'\2'"$TAB"'\3/p')
    [ -n "$_parsed" ] || return 1
    IFS="$TAB" read -r ROW_KEY ROW_INDEX ROW_VALUE <<EOF
$_parsed
EOF
}

read_flag() {
    _read_key=$1
    exchange "AT+GOOGGETNV=\"$_read_key\"" || return 1
    _matches=0
    VALUE=
    while IFS= read -r _row; do
        case $_row in
            *'+GOOGGETNV:'*)
                parse_nv_row "$_row" || return 1
                if [ "$ROW_KEY" = "$_read_key" ] && [ "$ROW_INDEX" = 0 ]; then
                    _matches=$((_matches + 1))
                    case $ROW_VALUE in 00|01) VALUE=$ROW_VALUE ;; *) return 1 ;; esac
                fi ;;
        esac
    done <"$REPLY"
    [ "$_matches" -eq 1 ] && { [ "$VALUE" = 00 ] || [ "$VALUE" = 01 ]; }
}

write_flag() {
    _write_key=$1
    _write_value=$2
    case $_write_key in "$MAIN_KEY"|"$DS_KEY") ;; *) return 1 ;; esac
    case $_write_value in 00|01) ;; *) return 1 ;; esac
    exchange "AT+GOOGSETNV=\"$_write_key\",0,\"$_write_value\"" || return 1
    read_flag "$_write_key" || return 1
    [ "$VALUE" = "$_write_value" ]
}

rollback() {
    ROLLBACK_RUNNING=1
    _rollback_failed=0
    say 'Restoring exact saved values for touched keys only...'
    while IFS="$TAB" read -r _rkey _rindex _rvalue; do
        [ -n "$_rkey" ] || continue
        if write_flag "$_rkey" "$_rvalue"; then
            say "Rollback verified: $_rkey index 0 = $_rvalue"
        else
            printf 'ROLLBACK FAILED: %s index 0; preserve %s\n' "$_rkey" "$RUN_DIR" >&2
            _rollback_failed=1
        fi
    done <"$RUN_DIR/touched.tsv"
    [ "$_rollback_failed" -eq 0 ]
}

on_exit() {
    _exit_status=$?
    trap - 0 INT TERM HUP
    if [ "$MUTATION_STARTED" -eq 1 ] && [ "$COMPLETED" -ne 1 ] && [ "$ROLLBACK_RUNNING" -ne 1 ]; then
        rollback || say 'Automatic rollback incomplete; use the saved backup after diagnosing transport.' >&2
        [ "$_exit_status" -ne 0 ] || _exit_status=1
    fi
    if [ "$LOCK_OWNED" -eq 1 ]; then
        # Never remove somebody else's/stale lock, even if our directory changed.
        if [ "$(cat "$LOCK_DIR/owner.pid" 2>/dev/null)" = "$$" ]; then
            rm -f "$LOCK_DIR/owner.pid"
            rmdir "$LOCK_DIR" 2>/dev/null || :
        elif [ ! -e "$LOCK_DIR/owner.pid" ]; then
            # If interrupted before writing ownership, remove only an empty lock.
            rmdir "$LOCK_DIR" 2>/dev/null || :
        fi
    fi
    exit "$_exit_status"
}
trap on_exit 0
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

mkdir "$LOCK_DIR" 2>/dev/null || die "Lock exists: $LOCK_DIR; inspect it, do not run concurrent AT clients"
LOCK_OWNED=1
printf '%s\n' "$$" >"$LOCK_DIR/owner.pid" || die 'Cannot save lock ownership'
RUN_DIR=$STATE_ROOT/run-$(date -u +%Y%m%dT%H%M%SZ)-$$
mkdir "$RUN_DIR" || die 'Cannot create a unique run directory'
say "Run directory: $RUN_DIR"
{
    printf 'mode=%s\nslot=%s\nport=%s\n' "$MODE" "$SLOT" "$PORT"
    if command -v getprop >/dev/null 2>&1; then
        for _prop in ro.product.model ro.product.device ro.build.version.release ro.build.version.sdk ro.build.id ro.build.fingerprint gsm.version.baseband; do
            printf '%s=%s\n' "$_prop" "$(getprop "$_prop")"
        done
    fi
} >"$RUN_DIR/metadata.txt" || die 'Cannot save metadata'

selected_keys() {
    case $SLOT in
        main) printf '%s\n' "$MAIN_KEY" ;;
        ds) printf '%s\n' "$DS_KEY" ;;
        both) printf '%s\n%s\n' "$MAIN_KEY" "$DS_KEY" ;;
    esac
}

validate_backup() {
    (
        _file=$1
        [ -f "$_file" ] && [ -r "$_file" ] || exit 1
        exec 4<"$_file" || exit 1
        IFS= read -r _header <&4 || exit 1
        [ "$_header" = P9PF_NRDC_BACKUP_V1 ] || exit 1
        _seen_main=0; _seen_ds=0; _count=0
        while :; do
            _backup_row=
            if IFS= read -r _backup_row <&4; then :
            else
                # Generated backups always end each row in LF. Reject partial
                # final rows so later plain read loops can never skip a flag.
                [ -z "$_backup_row" ] || exit 1
                break
            fi
            IFS="$TAB" read -r _bk _bi _bv _extra <<EOF
$_backup_row
EOF
            [ "$_bi" = 0 ] || exit 1
            case $_bv in 00|01) ;; *) exit 1 ;; esac
            # An exact reconstruction rejects extra fields/tabs or empty fields.
            [ "$_backup_row" = "$(printf '%s\t0\t%s' "$_bk" "$_bv")" ] || exit 1
            case $_bk in
                "$MAIN_KEY") [ "$_seen_main" -eq 0 ] || exit 1; _seen_main=1 ;;
                "$DS_KEY") [ "$_seen_ds" -eq 0 ] || exit 1; _seen_ds=1 ;;
                *) exit 1 ;;
            esac
            _count=$((_count + 1))
        done
        [ "$_count" -ge 1 ] && [ "$_count" -le 2 ]
    )
}

lookup_original() {
    ORIGINAL=
    while IFS="$TAB" read -r _bk _bi _bv; do
        if [ "$_bk" = "$1" ]; then ORIGINAL=$_bv; return 0; fi
    done <"$RUN_DIR/backup.tsv"
    return 1
}

if [ "$MODE" = audit ]; then
    _audit_failed=0
    selected_keys >"$RUN_DIR/selected.txt"
    while IFS= read -r _key; do
        if read_flag "$_key"; then say "READ $_key index 0 = $VALUE"
        else say "UNAVAILABLE/INVALID: $_key"; _audit_failed=1
        fi
    done <"$RUN_DIR/selected.txt"
    cat >"$RUN_DIR/optional.txt" <<EOF
$MAIN_KEY
$DS_KEY
OEM_GFEATURE_PIXEL_MMW_DISABLE_NEED_TO_DISABLE
OEM_GFEATURE_PIXEL_MMW_DISABLE_NEED_TO_DISABLE_DS
NR.CONFIG.MODE
DS.NR.CONFIG.MODE
PSS.GMC_NrRoamingDisableType
DS.PSS.GMC_NrRoamingDisableType
UECAPA_NR_RF_BAND_FR1_BM
UECAPA_NR_RF_BAND_FR1_BM_DS
UECAPA_NR_RF_BAND_FR2_BM
UECAPA_NR_RF_BAND_FR2_BM_DS
NRRRC.SIM_BASED_BAND_LIST_SUPPORT
!NRRRC.NUM_SUPPORTED_NR_BAND_LIST
OEM_GFEATURE_FCC_CT3_GLOBAL_MMW_JP_NRSA_BANDS
EOF
    while IFS= read -r _key; do
        if exchange "AT+GOOGGETNV=\"$_key\""; then
            while IFS= read -r _row; do
                case $_row in
                    *'+GOOGGETNV:'*)
                        if parse_nv_row "$_row" && [ "$ROW_KEY" = "$_key" ]; then
                            printf 'READ %s\n' "$_row"
                        fi ;;
                esac
            done <"$REPLY"
        else say "OPTIONAL unsupported/unavailable: $_key"
        fi
    done <"$RUN_DIR/optional.txt"
    say 'Audit finished: no NV writes, reboot or radio changes.'
    COMPLETED=1
    exit "$_audit_failed"
fi

if [ "$MODE" = restore ]; then
    validate_backup "$RESTORE_DIR/backup.tsv" || die 'Invalid backup schema/keys/indices/values; no NV write attempted'
    # Snapshot validated source data now; never source or execute backup contents.
    sed '1d' "$RESTORE_DIR/backup.tsv" >"$RUN_DIR/targets.tsv" || die 'Cannot snapshot restore targets'
    # Revalidate copied input to fail closed if the source changed during copying.
    { printf '%s\n' P9PF_NRDC_BACKUP_V1; cat "$RUN_DIR/targets.tsv"; } >"$RUN_DIR/source-check.tsv"
    validate_backup "$RUN_DIR/source-check.tsv" || die 'Restore source changed or is invalid'
else
    selected_keys >"$RUN_DIR/selected.txt" || die 'Cannot save selected keys'
    : >"$RUN_DIR/targets.tsv" || die 'Cannot prepare targets'
    while IFS= read -r _key; do
        printf '%s\t0\t01\n' "$_key" >>"$RUN_DIR/targets.tsv" || die 'Cannot save target'
    done <"$RUN_DIR/selected.txt"
fi

# Back up ALL selected current values before the first write. If one key cannot
# be read exactly, the entire operation stops with no writes.
printf '%s\n' P9PF_NRDC_BACKUP_V1 >"$RUN_DIR/backup.tmp" || die 'Cannot create backup'
while IFS="$TAB" read -r _key _index _target; do
    read_flag "$_key" || die "Cannot read exact current 00/01 value: $_key; no NV write attempted"
    printf '%s\t0\t%s\n' "$_key" "$VALUE" >>"$RUN_DIR/backup.tmp" || die 'Cannot save original value'
done <"$RUN_DIR/targets.tsv"
validate_backup "$RUN_DIR/backup.tmp" || die 'Backup validation failed'
mv "$RUN_DIR/backup.tmp" "$RUN_DIR/backup.tsv" || die 'Cannot commit backup'
sync || die 'Cannot flush backup; no NV write attempted'
: >"$RUN_DIR/touched.tsv" || die 'Cannot create touched journal'

while IFS="$TAB" read -r _key _index _target; do
    lookup_original "$_key" || die 'Original value missing from validated backup'
    _original=$ORIGINAL
    [ -n "$_original" ] || die 'Original value missing from validated backup'
    if [ "$_original" = "$_target" ]; then
        say "UNCHANGED: $_key index 0 = $_target"
        continue
    fi
    printf '%s\t0\t%s\n' "$_key" "$_original" >>"$RUN_DIR/touched.tsv" || die 'Cannot journal original value'
    sync || die 'Cannot flush touched journal; aborting before this write'
    MUTATION_STARTED=1
    write_flag "$_key" "$_target" || die "SET or exact readback failed: $_key"
    say "VERIFIED: $_key index 0 = $_target"
done <"$RUN_DIR/targets.tsv"
COMPLETED=1
say "Backup: $RUN_DIR/backup.tsv"
say 'NV operation verified only. No reboot/radio restart performed.'
say 'Audit again after your normal restart and validate UE capability plus actual CSL NRDC configuration.'
exit 0
