package dev.p9pf.nrdc;

import java.io.FileOutputStream;
import java.io.IOException;
import java.io.PrintStream;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/** A single-key, temporary CarrierConfig experiment; not an NRDC capability patch. */
public final class NrSaPolicy {
    public static final String KEY = "carrier_nr_availabilities_int_array";
    public static final String SCHEMA = "P9PF_SA_POLICY_V1";
    private static final int[] BASELINE = {1};
    private static final int[] TARGET = {1, 2};
    private static final long POLL_MILLIS = 10_000L;
    private static final String[] MODEL_PROPERTIES = {
        "ro.product.model", "ro.product.device", "ro.build.version.release",
        "ro.build.id", "gsm.version.baseband"
    };

    private NrSaPolicy() { }

    /** Narrow boundary so host tests can exercise transactions without Android. */
    public interface Backend {
        Identity identity(Integer requestedSlot) throws Exception;
        int[] read(int sub) throws Exception;
        void override(int sub, int[] value) throws Exception;
        long monotonicMillis();
        void sleep(long millis) throws Exception;
    }

    public static final class Identity {
        public final int slot;
        public final int sub;
        public final int defaultSub;

        public Identity(int slot, int sub, int defaultSub) {
            if ((slot != 0 && slot != 1) || sub < 0 || defaultSub < -1) {
                throw new IllegalArgumentException("Invalid subscription identity");
            }
            this.slot = slot;
            this.sub = sub;
            this.defaultSub = defaultSub;
        }

        public boolean same(Identity other) {
            return other != null && slot == other.slot && sub == other.sub
                && defaultSub == other.defaultSub;
        }
    }

    public static final class PolicyException extends Exception {
        public PolicyException(String message) { super(message); }
    }

    /** Strict data file; it is never sourced, interpreted, or deserialized as code. */
    public static final class Backup {
        public final int slot;
        public final int sub;

        public Backup(int slot, int sub) {
            new Identity(slot, sub, -1);
            this.slot = slot;
            this.sub = sub;
        }

        public String encode() {
            return "schema=" + SCHEMA + "\nslot=" + slot + "\nsub=" + sub
                + "\noriginal=1\ntarget=1,2\n";
        }

        public static Backup read(Path file) throws Exception {
            if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)
                    || Files.size(file) > 4096) {
                throw new PolicyException("Backup must be a small regular file");
            }
            byte[] bytes = Files.readAllBytes(file);
            for (byte b : bytes) {
                int c = b & 0xff;
                if (c != 10 && (c < 32 || c > 126)) {
                    throw new PolicyException("Invalid backup characters");
                }
            }
            String text = new String(bytes, StandardCharsets.US_ASCII);
            if (!text.endsWith("\n")) {
                throw new PolicyException("Backup must end with LF");
            }
            Map<String, String> fields = new LinkedHashMap<String, String>();
            for (String line : text.substring(0, text.length() - 1).split("\n", -1)) {
                int separator = line.indexOf('=');
                if (separator <= 0 || line.indexOf('=', separator + 1) >= 0) {
                    throw new PolicyException("Invalid backup row");
                }
                String name = line.substring(0, separator);
                String value = line.substring(separator + 1);
                if (!(name.equals("schema") || name.equals("slot") || name.equals("sub")
                        || name.equals("original") || name.equals("target"))
                        || fields.put(name, value) != null) {
                    throw new PolicyException("Unknown or duplicate backup field");
                }
            }
            if (fields.size() != 5 || !SCHEMA.equals(fields.get("schema"))
                    || !"1".equals(fields.get("original"))
                    || !"1,2".equals(fields.get("target"))
                    || !("0".equals(fields.get("slot")) || "1".equals(fields.get("slot")))
                    || fields.get("sub") == null
                    || !fields.get("sub").matches("0|[1-9][0-9]*")) {
                throw new PolicyException("Unsupported backup contents");
            }
            try {
                return new Backup(Integer.parseInt(fields.get("slot")),
                    Integer.parseInt(fields.get("sub")));
            } catch (IllegalArgumentException e) {
                throw new PolicyException("Invalid backup subscription identity");
            }
        }
    }

    public static final class Controller {
        private final Backend backend;
        private final PrintStream out;
        private final Object operationLock = new Object();
        private volatile boolean shutdownRequested;
        private Change active;

        private static final class Change {
            final Identity identity;
            final Integer requestedSlot;
            final Path run;
            boolean attempted;

            Change(Identity identity, Integer requestedSlot, Path run) {
                this.identity = identity;
                this.requestedSlot = requestedSlot;
                this.run = run;
            }
        }

        public Controller(Backend backend, PrintStream out) {
            this.backend = backend;
            this.out = out;
        }

        private void checkRunning() throws PolicyException {
            if (shutdownRequested) throw new PolicyException("Interrupted; restoring baseline when safe");
        }

        private Identity checkedIdentity(Integer requestedSlot) throws Exception {
            Identity identity = backend.identity(requestedSlot);
            if (identity == null || (requestedSlot != null && identity.slot != requestedSlot)) {
                throw new PolicyException("Subscription identity could not be verified");
            }
            return identity;
        }

        private void verifyIdentity(Identity expected, Integer requestedSlot) throws Exception {
            if (!expected.same(checkedIdentity(requestedSlot))) {
                throw new PolicyException("Subscription/default-data identity changed; refusing write");
            }
        }

        private int[] read(Identity identity) throws Exception {
            int[] value = backend.read(identity.sub);
            if (value == null || value.length == 0 || value.length > 16) {
                throw new PolicyException("NR availability key is absent or unsupported");
            }
            return value.clone();
        }

        private void printStatus(Identity identity, int[] array) {
            out.println("slot=" + identity.slot);
            out.println("sub=" + identity.sub);
            out.println("is_default_data=" + (identity.sub == identity.defaultSub));
            out.println(KEY + "=" + Arrays.toString(array));
        }

        public void status(Integer requestedSlot) throws Exception {
            synchronized (operationLock) {
                Identity identity = checkedIdentity(requestedSlot);
                int[] array = read(identity);
                verifyIdentity(identity, requestedSlot);
                printStatus(identity, array);
            }
        }

        /** Returns the saved backup path, or null if SA is already allowed. */
        public Path enable(Integer requestedSlot, Path stateRoot) throws Exception {
            synchronized (operationLock) {
                checkRunning();
                Identity identity = checkedIdentity(requestedSlot);
                int[] original = read(identity);
                verifyIdentity(identity, requestedSlot);
                printStatus(identity, original);
                for (int value : original) {
                    if (value == 2) {
                        out.println("NO_CHANGE: SA is already allowed by the merged key.");
                        return null;
                    }
                }
                if (!Arrays.equals(original, BASELINE)) {
                    throw new PolicyException("Enable supports only the exact current array [1]");
                }
                Path run = privateRun(stateRoot);
                Path backup = run.resolve("backup.properties");
                writeNewDurable(backup, new Backup(identity.slot, identity.sub).encode());
                // Parse what was actually persisted before attempting any mutation.
                Backup.read(backup);
                journal(run, "PREPARED", identity);
                out.println("Backup: " + backup);
                verifyIdentity(identity, requestedSlot);
                if (!Arrays.equals(read(identity), original)) {
                    throw new PolicyException("NR policy changed after backup; no write attempted");
                }
                verifyIdentity(identity, requestedSlot);
                checkRunning();
                Change change = new Change(identity, requestedSlot, run);
                active = change;
                boolean completed = false;
                try {
                    journal(run, "WRITE_ATTEMPTED", identity);
                    checkRunning();
                    change.attempted = true;
                    backend.override(identity.sub, TARGET.clone());
                    await(identity, requestedSlot, TARGET, true);
                    checkRunning();
                    journal(run, "ENABLED_VERIFIED", identity);
                    checkRunning();
                    completed = true;
                    out.println("VERIFIED: merged key is [1, 2]; this does not prove NRDC.");
                    out.println("Temporary override only; no reboot or radio toggle was performed.");
                    return backup;
                } finally {
                    if (!completed && change.attempted) {
                        recover(change);
                    }
                    active = null;
                }
            }
        }

        /** Restore the single saved effective value; never clear an override bundle. */
        public void restore(Path backupFile, Integer requestedSlot, Path stateRoot) throws Exception {
            synchronized (operationLock) {
                checkRunning();
                Backup backup = Backup.read(backupFile);
                if (requestedSlot != null && requestedSlot != backup.slot) {
                    throw new PolicyException("Requested slot differs from backup");
                }
                Integer slot = Integer.valueOf(backup.slot);
                Identity identity = checkedIdentity(slot);
                if (identity.sub != backup.sub) {
                    throw new PolicyException("Backup subscription no longer occupies its saved slot");
                }
                int[] current = read(identity);
                verifyIdentity(identity, slot);
                printStatus(identity, current);
                if (Arrays.equals(current, BASELINE)) {
                    out.println("NO_CHANGE: saved baseline [1] is already effective.");
                    return;
                }
                if (!Arrays.equals(current, TARGET)) {
                    throw new PolicyException("Current policy differs from our exact target [1, 2]; restore refused");
                }
                Path run = privateRun(stateRoot);
                writeNewDurable(run.resolve("backup.properties"), backup.encode());
                journal(run, "RESTORE_PREPARED", identity);
                Change change = new Change(identity, slot, run);
                active = change;
                boolean completed = false;
                try {
                    verifyIdentity(identity, slot);
                    if (!Arrays.equals(read(identity), TARGET)) {
                        throw new PolicyException("NR policy changed before restore; refusing write");
                    }
                    verifyIdentity(identity, slot);
                    checkRunning();
                    journal(run, "RESTORE_ATTEMPTED", identity);
                    checkRunning();
                    change.attempted = true;
                    backend.override(identity.sub, BASELINE.clone());
                    await(identity, slot, BASELINE, true);
                    checkRunning();
                    journal(run, "RESTORED_VERIFIED", identity);
                    completed = true;
                    out.println("VERIFIED: saved effective array [1] restored for the same subscription.");
                    out.println("The copied old value remains in the temporary layer until normal reboot.");
                    out.println("Other override keys were not cleared or copied.");
                } finally {
                    if (!completed && change.attempted) recover(change);
                    active = null;
                }
            }
        }

        private void await(Identity identity, Integer requestedSlot, int[] target,
                boolean respectInterruption) throws Exception {
            long start = backend.monotonicMillis();
            int maximumPolls = 41; // Also bounded when a fake or broken clock does not advance.
            while (maximumPolls-- > 0) {
                if (respectInterruption) checkRunning();
                verifyIdentity(identity, requestedSlot);
                int[] current = read(identity);
                if (Arrays.equals(current, target)) {
                    verifyIdentity(identity, requestedSlot);
                    return;
                }
                long elapsed = backend.monotonicMillis() - start;
                if (elapsed < 0 || elapsed >= POLL_MILLIS || maximumPolls == 0) break;
                backend.sleep(Math.min(250L, POLL_MILLIS - elapsed));
            }
            throw new PolicyException("Merged-key verification timed out; preserve the backup");
        }

        private void recover(Change change) {
            try {
                verifyIdentity(change.identity, change.requestedSlot);
                int[] current = read(change.identity);
                if (Arrays.equals(current, BASELINE)) {
                    // An earlier asynchronous target write may still be queued.
                    // Enqueue the baseline AFTER it, without claiming an unchanged
                    // merged value proves that either queued message has run.
                    verifyIdentity(change.identity, change.requestedSlot);
                    if (!Arrays.equals(read(change.identity), BASELINE)) {
                        throw new PolicyException("NR key changed before recovery fence; refusing write");
                    }
                    verifyIdentity(change.identity, change.requestedSlot);
                    journal(change.run, "RECOVERY_FENCE_ATTEMPTED", change.identity);
                    backend.override(change.identity.sub, BASELINE.clone());
                    journal(change.run, "RECOVERY_FENCE_ENQUEUED", change.identity);
                    out.println("RECOVERY UNCONFIRMED: baseline [1] was already visible, but an earlier target write may still be queued.");
                    out.println("A baseline-only override was enqueued after the attempt; unchanged readback cannot prove completion.");
                    out.println("Preserve backup/journal and check status again: " + change.run);
                    return;
                }
                if (!Arrays.equals(current, TARGET)) {
                    throw new PolicyException("Current key changed externally; recovery refused");
                }
                // Recheck both value and identity immediately before the merge-only write.
                verifyIdentity(change.identity, change.requestedSlot);
                if (!Arrays.equals(read(change.identity), TARGET)) {
                    throw new PolicyException("Current key changed before recovery; refusing write");
                }
                verifyIdentity(change.identity, change.requestedSlot);
                journal(change.run, "RECOVERY_ATTEMPTED", change.identity);
                backend.override(change.identity.sub, BASELINE.clone());
                await(change.identity, change.requestedSlot, BASELINE, false);
                journal(change.run, "RECOVERED_VERIFIED", change.identity);
                out.println("RECOVERY VERIFIED: saved effective array [1] restored.");
                out.println("A temporary copy of [1] remains until normal reboot; no other keys were cleared.");
            } catch (Exception recoveryFailure) {
                out.println("RECOVERY UNCONFIRMED: " + safeMessage(recoveryFailure));
                out.println("Preserve backup and journal in: " + change.run);
            }
        }

        /** Hook sets cancellation before waiting, so main never races a recovery writer. */
        public void requestShutdownAndRecover() {
            shutdownRequested = true;
            synchronized (operationLock) {
                if (active != null && active.attempted) {
                    recover(active);
                    active = null;
                }
            }
        }
    }

    private static Path privateRun(Path stateRoot) throws Exception {
        if (stateRoot == null || !stateRoot.isAbsolute()) {
            throw new PolicyException("State root must be an absolute directory");
        }
        Files.createDirectories(stateRoot, PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rwx------")));
        if (!Files.isDirectory(stateRoot, LinkOption.NOFOLLOW_LINKS)) {
            throw new PolicyException("State root must not be a symlink");
        }
        return Files.createTempDirectory(stateRoot, "run-", PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rwx------")));
    }

    private static void writeNewDurable(Path file, String contents) throws IOException {
        Files.createFile(file, PosixFilePermissions.asFileAttribute(
            PosixFilePermissions.fromString("rw-------")));
        try (FileOutputStream stream = new FileOutputStream(file.toFile())) {
            stream.write(contents.getBytes(StandardCharsets.US_ASCII));
            stream.flush();
            stream.getFD().sync();
        }
    }

    private static void journal(Path run, String stage, Identity identity) throws IOException {
        Path temporary = Files.createTempFile(run, ".journal-", ".tmp",
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        boolean moved = false;
        try {
            try (FileOutputStream stream = new FileOutputStream(temporary.toFile())) {
                String text = "schema=P9PF_SA_JOURNAL_V1\nstage=" + stage + "\nslot="
                    + identity.slot + "\nsub=" + identity.sub + "\n";
                stream.write(text.getBytes(StandardCharsets.US_ASCII));
                stream.flush();
                stream.getFD().sync();
            }
            Files.move(temporary, run.resolve("journal.properties"),
                StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            moved = true;
        } finally {
            if (!moved) Files.deleteIfExists(temporary);
        }
    }

    /** Android classes are looked up at runtime; javac needs no Android SDK jar. */
    public static final class ReflectionBackend implements Backend {
        private final Object loader;
        private final Object subscriptions;
        private final Class<?> loaderInterface;
        private final Class<?> subInterface;
        private final Class<?> bundleClass;

        public ReflectionBackend() throws Exception {
            Class<?> process = Class.forName("android.os.Process");
            if (((Integer) invoke(process.getMethod("myUid"), null)).intValue() != 0) {
                throw new PolicyException("Root app_process UID 0 is required");
            }
            bundleClass = Class.forName("android.os.PersistableBundle");
            loaderInterface = Class.forName("com.android.internal.telephony.ICarrierConfigLoader");
            subInterface = Class.forName("com.android.internal.telephony.ISub");
            loader = binderService("carrier_config", loaderInterface);
            subscriptions = binderService("isub", subInterface);
        }

        private static Object binderService(String service, Class<?> interfaceClass) throws Exception {
            Class<?> binderClass = Class.forName("android.os.IBinder");
            Class<?> managerClass = Class.forName("android.os.ServiceManager");
            Object binder = invoke(managerClass.getMethod("getService", String.class), null, service);
            if (binder == null) throw new PolicyException("Required Binder service unavailable: " + service);
            Class<?> stub = Class.forName(interfaceClass.getName() + "$Stub");
            Object proxy = invoke(stub.getMethod("asInterface", binderClass), null, binder);
            if (proxy == null) throw new PolicyException("Required Binder interface unavailable: " + service);
            return proxy;
        }

        private int subCall(String name, Class<?>[] parameterTypes, Object... arguments) throws Exception {
            return ((Integer) invoke(subInterface.getMethod(name, parameterTypes),
                subscriptions, arguments)).intValue();
        }

        @Override public Identity identity(Integer requestedSlot) throws Exception {
            int defaultSub = subCall("getDefaultDataSubId", new Class<?>[0]);
            int sub = requestedSlot == null ? defaultSub
                : subCall("getSubId", new Class<?>[] {int.class}, requestedSlot);
            if (sub < 0) throw new PolicyException("No active selected/default-data subscription");
            int slot = subCall("getSlotIndex", new Class<?>[] {int.class}, Integer.valueOf(sub));
            if ((slot != 0 && slot != 1) || (requestedSlot != null && slot != requestedSlot)) {
                throw new PolicyException("Selected subscription has no supported logical slot");
            }
            int roundTrip = subCall("getSubId", new Class<?>[] {int.class}, Integer.valueOf(slot));
            if (roundTrip != sub) throw new PolicyException("Subscription/slot round-trip failed");
            return new Identity(slot, sub, defaultSub);
        }

        @Override public int[] read(int sub) throws Exception {
            Object bundle = invoke(loaderInterface.getMethod("getConfigForSubIdWithFeature",
                int.class, String.class, String.class), loader, Integer.valueOf(sub), null, null);
            if (bundle == null) throw new PolicyException("CarrierConfig returned no merged bundle");
            Object value = invoke(bundleClass.getMethod("getIntArray", String.class), bundle, KEY);
            if (value == null) return null;
            if (!(value instanceof int[])) throw new PolicyException("NR key has unsupported type");
            return ((int[]) value).clone();
        }

        @Override public void override(int sub, int[] value) throws Exception {
            Object bundle = bundleClass.getConstructor().newInstance();
            invoke(bundleClass.getMethod("putIntArray", String.class, int[].class),
                bundle, KEY, value.clone());
            // Non-null single-key bundle; false always means non-persistent.
            invoke(loaderInterface.getMethod("overrideConfig", int.class, bundleClass, boolean.class),
                loader, Integer.valueOf(sub), bundle, Boolean.FALSE);
        }

        @Override public long monotonicMillis() { return System.nanoTime() / 1_000_000L; }
        @Override public void sleep(long millis) throws InterruptedException { Thread.sleep(millis); }
    }

    private static Object invoke(Method method, Object receiver, Object... arguments) throws Exception {
        try {
            return method.invoke(receiver, arguments);
        } catch (InvocationTargetException wrapped) {
            Throwable cause = wrapped.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw wrapped;
        }
    }

    private static String safeMessage(Exception exception) {
        if (exception instanceof PolicyException) return exception.getMessage();
        return exception.getClass().getSimpleName() + " (Binder/filesystem operation failed)";
    }

    private static void modelProperties(PrintStream out) {
        try {
            Method get = Class.forName("android.os.SystemProperties").getMethod("get", String.class);
            for (String key : MODEL_PROPERTIES) {
                String value = String.valueOf(invoke(get, null, key));
                // Never allow multiline property text to masquerade as report fields.
                out.println(key + "=" + value.replace('\n', ' ').replace('\r', ' '));
            }
        } catch (Exception ignored) {
            out.println("model_properties=unavailable");
        }
    }

    private static void usage(PrintStream out) {
        out.println("NrSaPolicy [status|enable|restore BACKUPFILE] [--slot 0|1] [--state-root ABS_DIR]");
        out.println("Default: status for the default-data subscription. Root UID 0 required.");
        out.println("Only [1] -> [1,2] is enabled, temporarily. No reboot, radio toggle or NRDC guarantee.");
    }

    public static int run(String[] arguments, PrintStream out, PrintStream err) {
        try {
            String mode = "status";
            Path backup = null;
            Integer slot = null;
            Path stateRoot = Paths.get("/data/local/tmp/p9pf-nrdc/sa-policy");
            int index = 0;
            if (arguments.length > 0 && !arguments[0].startsWith("--")) {
                mode = arguments[index++];
                if (mode.equals("restore")) {
                    if (index >= arguments.length || arguments[index].startsWith("--")) {
                        throw new PolicyException("restore requires BACKUPFILE");
                    }
                    backup = Paths.get(arguments[index++]);
                }
            }
            if (!(mode.equals("status") || mode.equals("enable") || mode.equals("restore"))) {
                throw new PolicyException("Unknown operation");
            }
            while (index < arguments.length) {
                String option = arguments[index++];
                if (option.equals("--help")) { usage(out); return 0; }
                if (index >= arguments.length) throw new PolicyException("Missing option value");
                String value = arguments[index++];
                if (option.equals("--slot")) {
                    if (!(value.equals("0") || value.equals("1"))) {
                        throw new PolicyException("--slot must be 0 or 1");
                    }
                    if (slot != null) throw new PolicyException("Duplicate --slot");
                    slot = Integer.valueOf(value);
                } else if (option.equals("--state-root")) {
                    stateRoot = Paths.get(value);
                    if (!stateRoot.isAbsolute()) throw new PolicyException("State root must be absolute");
                } else {
                    throw new PolicyException("Unknown option");
                }
            }
            final Controller controller = new Controller(new ReflectionBackend(), out);
            Thread recoveryHook = new Thread(new Runnable() {
                @Override public void run() { controller.requestShutdownAndRecover(); }
            }, "p9pf-sa-policy-recovery");
            Runtime.getRuntime().addShutdownHook(recoveryHook);
            try {
                modelProperties(out);
                if (mode.equals("status")) controller.status(slot);
                else if (mode.equals("enable")) controller.enable(slot, stateRoot);
                else controller.restore(backup, slot, stateRoot);
            } finally {
                try { Runtime.getRuntime().removeShutdownHook(recoveryHook); }
                catch (IllegalStateException shuttingDown) { /* Registered hook owns shutdown recovery. */ }
            }
            return 0;
        } catch (Exception exception) {
            err.println("ERROR: " + safeMessage(exception));
            return 1;
        }
    }

    public static void main(String[] arguments) {
        System.exit(run(arguments, System.out, System.err));
    }
}
