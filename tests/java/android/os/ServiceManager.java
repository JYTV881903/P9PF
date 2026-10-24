package android.os;
import java.util.LinkedHashMap;
import java.util.Map;
/** Host-test stub, never included in the Android helper artifact. */
public final class ServiceManager {
    public static final Map<String, IBinder> services = new LinkedHashMap<String, IBinder>();
    public static IBinder getService(String name) { return services.get(name); }
}
