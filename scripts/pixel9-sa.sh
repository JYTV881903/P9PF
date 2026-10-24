#!/system/bin/sh
# Root app_process entry; changes only one temporary CarrierConfig key.
if [ -x /system/bin/sh ]; then
    PATH=/system/bin:/system/xbin:/vendor/bin
    export PATH
fi
[ "$(id -u)" = 0 ] || { echo 'A root terminal is required. Type su first.' >&2; exit 1; }
APP_PROCESS=/system/bin/app_process
[ -x "$APP_PROCESS" ] || { echo 'Android app_process is unavailable; no policy change attempted.' >&2; exit 1; }
SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" && pwd) || exit 1
JAR=$SCRIPT_DIR/../android/nr-sa-policy.jar
MANIFEST=$SCRIPT_DIR/../android/nr-sa-policy.sha256
[ -r "$JAR" ] && [ -r "$MANIFEST" ] || { echo 'Download/extract the complete updated GitHub ZIP, including android/.' >&2; exit 1; }
for _tool in sha256sum mkdir cp chmod mv timeout cat rm rmdir; do
    command -v "$_tool" >/dev/null 2>&1 || { echo "Missing system utility: $_tool" >&2; exit 1; }
done
read -r EXPECTED NAME EXTRA <"$MANIFEST"
case $EXPECTED in ''|*[!0-9a-f]*) echo 'Invalid helper checksum manifest.' >&2; exit 1 ;; esac
[ "${#EXPECTED}" -eq 64 ] && [ "$NAME" = nr-sa-policy.jar ] && [ -z "$EXTRA" ] || exit 1
ACTUAL=$(sha256sum "$JAR") || exit 1
ACTUAL=${ACTUAL%% *}
[ "$ACTUAL" = "$EXPECTED" ] || { echo 'Helper checksum mismatch; no policy change attempted.' >&2; exit 1; }

STATE_ROOT=${P9PF_STATE_ROOT:-/data/local/tmp/p9pf-nrdc}
case $STATE_ROOT in /*) ;; *) echo 'State root must be absolute.' >&2; exit 1 ;; esac
umask 077
CACHE=$STATE_ROOT/sa-runtime
mkdir -p "$CACHE" || exit 1
LOCK=$CACHE/operation.lock
mkdir "$LOCK" 2>/dev/null || { echo 'Another SA policy operation or its lock exists; no policy change attempted.' >&2; exit 1; }
TEMPORARY=
cleanup() {
    if [ -n "$TEMPORARY" ]; then rm -f "$TEMPORARY"; fi
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
STAGED=$CACHE/nr-sa-policy-$EXPECTED.jar
if [ -e "$STAGED" ]; then
    CURRENT=$(sha256sum "$STAGED") || exit 1
    [ "${CURRENT%% *}" = "$EXPECTED" ] || { echo 'Existing staged helper differs; refusing it.' >&2; exit 1; }
else
    CANDIDATE=$CACHE/stage-$$.jar
    [ ! -e "$CANDIDATE" ] || exit 1
    TEMPORARY=$CANDIDATE
    cp "$JAR" "$TEMPORARY" || exit 1
    COPIED=$(sha256sum "$TEMPORARY") || exit 1
    [ "${COPIED%% *}" = "$EXPECTED" ] || { echo 'Copied helper checksum mismatch; refusing execution.' >&2; exit 1; }
    chmod 444 "$TEMPORARY" && mv "$TEMPORARY" "$STAGED" || exit 1
    TEMPORARY=
fi
chmod 444 "$STAGED" || exit 1
FINAL=$(sha256sum "$STAGED") || exit 1
[ "${FINAL%% *}" = "$EXPECTED" ] || { echo 'Staged helper checksum mismatch; refusing execution.' >&2; exit 1; }
# Loading a read-only DEX from private root storage avoids shared-storage noexec
# and writable-code restrictions. Binder/root permission failures remain errors.
CLASSPATH=$STAGED
export CLASSPATH
timeout -s 9 40 "$APP_PROCESS" /system/bin dev.p9pf.nrdc.NrSaPolicy "$@"
RESULT=$?
exit "$RESULT"
