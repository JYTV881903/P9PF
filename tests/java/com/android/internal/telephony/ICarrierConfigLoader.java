package com.android.internal.telephony;
import android.os.IBinder;
import android.os.PersistableBundle;
/** Exact inspected Binder surface; this stub is host-test-only. */
public interface ICarrierConfigLoader {
    PersistableBundle getConfigForSubIdWithFeature(int sub, String pkg, String feature);
    void overrideConfig(int sub, PersistableBundle values, boolean persistent);
    abstract class Stub {
        public static ICarrierConfigLoader asInterface(IBinder binder) {
            return (ICarrierConfigLoader) binder;
        }
    }
}
