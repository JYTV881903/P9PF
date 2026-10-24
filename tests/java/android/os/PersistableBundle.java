package android.os;
import java.util.LinkedHashMap;
import java.util.Map;
/** Host-test stub, never included in the Android helper artifact. */
public final class PersistableBundle {
    public final Map<String, int[]> values = new LinkedHashMap<String, int[]>();
    public void putIntArray(String key, int[] value) { values.put(key, value.clone()); }
    public int[] getIntArray(String key) {
        int[] value = values.get(key);
        return value == null ? null : value.clone();
    }
}
