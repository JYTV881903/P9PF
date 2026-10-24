#!/system/bin/sh
# Read-only Android16 CarrierConfig audit. Run this script ON the phone.
# No full dump is saved or sent over ADB: only exact NR keys and layer labels pass.
# "Phone Id" is a logical slot; mNoSimConfig is NOT an active SIM's merged policy.
# Per phone, later non-null layers override earlier ones in the printed order.
# SA=2 in the effective availability list removes one policy block; it is not NRDC proof.
set -o pipefail

command -v timeout >/dev/null 2>&1 || { echo 'timeout unavailable; carrier policy remains unknown.' >&2; exit 1; }
timeout -s 9 10 dumpsys carrier_config | grep -E '^[[:space:]]*(Phone Id = [0-9]+[[:space:]]*$|Default Values from CarrierConfigManager[[:space:]]*:|mConfigFrom(DefaultApp|CarrierApp)[[:space:]]*:|m(PersistentOverrideConfigs|OverrideConfigs|NoSimConfig)[[:space:]]*:|carrier_nr_availabilities_int_array[[:space:]]*=|additional_nr_advanced_bands_int_array[[:space:]]*=|Permission Denial:)'
