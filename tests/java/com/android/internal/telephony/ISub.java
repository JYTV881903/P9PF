package com.android.internal.telephony;
import android.os.IBinder;
/** Exact inspected Binder surface; this stub is host-test-only. */
public interface ISub {
    int getDefaultDataSubId();
    int getSubId(int slot);
    int getSlotIndex(int sub);
    abstract class Stub {
        public static ISub asInterface(IBinder binder) { return (ISub) binder; }
    }
}
