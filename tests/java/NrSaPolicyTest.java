package dev.p9pf.nrdc;

import android.os.IBinder;
import android.os.PersistableBundle;
import android.os.ServiceManager;
import com.android.internal.telephony.ICarrierConfigLoader;
import com.android.internal.telephony.ISub;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Tests the transaction contract, not a real Android framework or live modem. */
public final class NrSaPolicyTest {
    static final String OTHER = "unrelated_override_key";
    static Path state;

    static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    static void array(int[] actual, int... expected) {
        require(Arrays.equals(actual, expected), "Array mismatch: " + Arrays.toString(actual));
    }

    interface Action { void run() throws Exception; }

    static void fails(Action action) throws Exception {
        boolean failed = false;
        try { action.run(); } catch (Exception expected) { failed = true; }
        require(failed, "Expected an operation failure");
    }

    static final class Write {
        final int sub;
        final int[] value;
        Write(int sub, int[] value) { this.sub = sub; this.value = value.clone(); }
    }

    static class Fake implements NrSaPolicy.Backend {
        NrSaPolicy.Identity selected = new NrSaPolicy.Identity(0, 7, 7);
        final Map<Integer, int[]> values = new LinkedHashMap<Integer, int[]>();
        final Map<String, int[]> unrelated = new LinkedHashMap<String, int[]>();
        final List<Write> writes = new ArrayList<Write>();
        final List<Write> queue = new ArrayList<Write>();
        long now;
        int reads;
        int identities;
        int switchAtIdentity;
        int changeAtRead;
        int[] changedValue;
        int applyAfterSleeps;
        int sleeps;
        boolean deny;
        boolean throwAfterApply;
        boolean throwAfterEnqueue;
        boolean requireBackup;
        boolean frozenClock;

        Fake(int... initial) {
            values.put(7, initial.clone());
            values.put(8, new int[] {1, 2});
            unrelated.put(OTHER, new int[] {91, 92});
        }

        @Override public NrSaPolicy.Identity identity(Integer requestedSlot) {
            identities++;
            if (switchAtIdentity != 0 && identities >= switchAtIdentity) {
                return new NrSaPolicy.Identity(0, 99, 99);
            }
            return selected;
        }

        @Override public int[] read(int sub) {
            reads++;
            if (changeAtRead != 0 && reads >= changeAtRead) values.put(sub, changedValue.clone());
            int[] value = values.get(sub);
            return value == null ? null : value.clone();
        }

        @Override public void override(int sub, int[] value) throws Exception {
            require(sub == 7, "Write retargeted an unexpected subscription");
            require(value != null, "A null bundle/value must never clear all overrides");
            require(Arrays.equals(value, new int[] {1}) || Arrays.equals(value, new int[] {1, 2}),
                "Unexpected array write");
            if (requireBackup && writes.isEmpty()) {
                List<Path> backups = filesNamed(state, "backup.properties");
                require(backups.size() == 1, "Durable backup must precede the first write");
                NrSaPolicy.Backup backup = NrSaPolicy.Backup.read(backups.get(0));
                require(backup.slot == 0 && backup.sub == 7, "Backup identity mismatch");
                require(Files.isRegularFile(backups.get(0).getParent().resolve("journal.properties")),
                    "Durable journal must precede mutation");
                require(Files.getPosixFilePermissions(backups.get(0)).equals(
                    PosixFilePermissions.fromString("rw-------")), "Backup must be private");
            }
            writes.add(new Write(sub, value));
            if (deny) throw new SecurityException("denied");
            if (throwAfterEnqueue && writes.size() == 1) {
                queue.add(new Write(sub, value));
                throw new IllegalStateException("Ack lost while queued");
            }
            if (!queue.isEmpty() || applyAfterSleeps != 0) queue.add(new Write(sub, value));
            else values.put(sub, value.clone());
            if (throwAfterApply && writes.size() == 1) {
                throw new IllegalStateException("Ack lost after apply");
            }
        }

        @Override public long monotonicMillis() { return frozenClock ? 0 : now; }
        @Override public void sleep(long millis) {
            now += millis;
            sleeps++;
            if (applyAfterSleeps != 0 && sleeps >= applyAfterSleeps) drain();
        }

        void drain() {
            for (Write write : queue) values.put(write.sub, write.value.clone());
            queue.clear();
        }

        void assertUnrelated() {
            array(unrelated.get(OTHER), 91, 92);
            array(values.get(8), 1, 2);
        }
    }

    static List<Path> filesNamed(Path root, final String name) throws Exception {
        final List<Path> result = new ArrayList<Path>();
        if (!Files.exists(root)) return result;
        try (java.util.stream.Stream<Path> stream = Files.walk(root)) {
            stream.filter(path -> path.getFileName().toString().equals(name)).forEach(result::add);
        }
        return result;
    }

    static NrSaPolicy.Controller controller(Fake fake, ByteArrayOutputStream output) {
        return new NrSaPolicy.Controller(fake, new PrintStream(output));
    }

    static Path backup(int slot, int sub) throws Exception {
        Path path = Files.createTempFile(state.getParent(), "input-backup-", ".properties");
        Files.write(path, new NrSaPolicy.Backup(slot, sub).encode().getBytes(StandardCharsets.US_ASCII));
        return path;
    }

    static void status() throws Exception {
        Fake fake = new Fake(1);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        controller(fake, output).status(null);
        require(fake.writes.isEmpty(), "Status wrote a value");
        require(!Files.exists(state), "Status created state");
        String report = output.toString("UTF-8");
        require(report.contains("slot=0") && report.contains("sub=7")
            && report.contains("is_default_data=true") && report.contains("[1]"), "Status incomplete");
        require(!report.contains(OTHER), "Unrelated property leaked");
    }

    static void noop() throws Exception {
        Fake fake = new Fake(1, 2);
        require(controller(fake, new ByteArrayOutputStream()).enable(null, state) == null,
            "SA allowed should be a no-op");
        require(fake.writes.isEmpty() && !Files.exists(state), "No-op created a mutation/backup");
    }

    static void enable() throws Exception {
        Fake fake = new Fake(1);
        fake.requireBackup = true;
        Path saved = controller(fake, new ByteArrayOutputStream()).enable(null, state);
        require(saved != null && Files.isRegularFile(saved), "Missing saved backup");
        require(fake.writes.size() == 1, "Enable wrote more than the target key once");
        array(fake.values.get(7), 1, 2);
        fake.assertUnrelated();
    }

    static void asynchronous() throws Exception {
        Fake fake = new Fake(1);
        fake.applyAfterSleeps = 3;
        controller(fake, new ByteArrayOutputStream()).enable(null, state);
        require(fake.sleeps >= 3 && fake.now <= 10000, "Async verification did not poll within deadline");
        array(fake.values.get(7), 1, 2);
    }

    static void unsupported() throws Exception {
        Fake fake = new Fake(3);
        fails(() -> controller(fake, new ByteArrayOutputStream()).enable(null, state));
        require(fake.writes.isEmpty(), "Unsupported array was written");
    }

    static void switchedBeforeWrite() throws Exception {
        Fake fake = new Fake(1);
        fake.switchAtIdentity = 3;
        fails(() -> controller(fake, new ByteArrayOutputStream()).enable(null, state));
        require(fake.writes.isEmpty(), "Identity switch did not block the write");
    }

    static void changedBeforeWrite() throws Exception {
        Fake fake = new Fake(1);
        fake.changeAtRead = 2;
        fake.changedValue = new int[] {3};
        fails(() -> controller(fake, new ByteArrayOutputStream()).enable(null, state));
        require(fake.writes.isEmpty(), "Policy changed after backup but helper still wrote");
    }

    static void restore() throws Exception {
        Fake fake = new Fake(1, 2);
        Path saved = backup(0, 7);
        controller(fake, new ByteArrayOutputStream()).restore(saved, null, state);
        array(fake.values.get(7), 1);
        fake.assertUnrelated();
    }

    static void restoreBinding() throws Exception {
        Fake fake = new Fake(1, 2);
        Path saved = backup(0, 99);
        fails(() -> controller(fake, new ByteArrayOutputStream()).restore(saved, null, state));
        require(fake.writes.isEmpty(), "Restore accepted a different subscription");
    }

    static void restoreChangedTarget() throws Exception {
        Fake fake = new Fake(2, 3);
        Path saved = backup(0, 7);
        fails(() -> controller(fake, new ByteArrayOutputStream()).restore(saved, null, state));
        require(fake.writes.isEmpty(), "Restore overwrote an externally changed array");
    }

    static void malformedBackup() throws Exception {
        String valid = new NrSaPolicy.Backup(0, 7).encode();
        String[] texts = {valid + "slot=0\n", valid + "unknown=1\n",
            valid.replace("original=1", "original=$(touch /never-execute)"),
            valid.substring(0, valid.length() - 1), valid.replace("sub=7", "sub=+7")};
        for (String text : texts) {
            Path file = Files.createTempFile(state.getParent(), "invalid-", ".txt");
            Files.write(file, text.getBytes(StandardCharsets.US_ASCII));
            fails(() -> NrSaPolicy.Backup.read(file));
        }
    }

    static void appliedThenThrow() throws Exception {
        Fake fake = new Fake(1);
        fake.throwAfterApply = true;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        fails(() -> controller(fake, output).enable(null, state));
        array(fake.values.get(7), 1);
        require(fake.writes.size() == 2, "Applied write did not trigger a recovery write");
        require(output.toString("UTF-8").contains("RECOVERY VERIFIED"), "Verified recovery not reported");
        fake.assertUnrelated();
    }

    static void queuedThenThrow() throws Exception {
        Fake fake = new Fake(1);
        fake.throwAfterEnqueue = true;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        fails(() -> controller(fake, output).enable(null, state));
        require(fake.queue.size() == 2, "Queued target must be fenced by a later baseline write");
        array(fake.queue.get(0).value, 1, 2);
        array(fake.queue.get(1).value, 1);
        String report = output.toString("UTF-8");
        require(report.contains("RECOVERY UNCONFIRMED") && !report.contains("RECOVERY VERIFIED"),
            "Unchanged baseline falsely reported a completed asynchronous recovery");
        fake.drain();
        array(fake.values.get(7), 1);
    }

    static void denied() throws Exception {
        Fake fake = new Fake(1);
        fake.deny = true;
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        fails(() -> controller(fake, output).enable(null, state));
        array(fake.values.get(7), 1);
        require(output.toString("UTF-8").contains("RECOVERY UNCONFIRMED"), "Denial hidden");
    }

    static void boundedTimeout() throws Exception {
        Fake fake = new Fake(1);
        fake.applyAfterSleeps = 999;
        fake.frozenClock = true;
        fails(() -> controller(fake, new ByteArrayOutputStream()).enable(null, state));
        require(fake.sleeps <= 40, "Polling was not bounded with a frozen clock");
        require(fake.queue.size() == 2, "Timed-out queued target lacks baseline fence");
    }

    static void switchedAfterApply() throws Exception {
        Fake fake = new Fake(1) {
            @Override public void override(int sub, int[] value) throws Exception {
                super.override(sub, value);
                selected = new NrSaPolicy.Identity(0, 99, 99);
            }
        };
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        fails(() -> controller(fake, output).enable(null, state));
        require(fake.writes.size() == 1, "Recovery retargeted a changed subscription");
        require(output.toString("UTF-8").contains("RECOVERY UNCONFIRMED"),
            "Identity-blocked recovery was falsely reported complete");
    }

    static void shutdownRequest() throws Exception {
        final NrSaPolicy.Controller[] owner = new NrSaPolicy.Controller[1];
        final Thread[] hook = new Thread[1];
        Fake fake = new Fake(1) {
            @Override public void override(int sub, int[] value) throws Exception {
                super.override(sub, value);
                if (writes.size() != 1) return;
                hook[0] = new Thread(() -> owner[0].requestShutdownAndRecover());
                hook[0].start();
                long deadline = System.nanoTime() + 2_000_000_000L;
                while (hook[0].getState() != Thread.State.BLOCKED) {
                    require(System.nanoTime() < deadline, "Recovery hook failed to wait on operation lock");
                    Thread.sleep(1L);
                }
                // The hook sets cancellation before blocking on the operation lock.
            }
        };
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        owner[0] = controller(fake, output);
        fails(() -> owner[0].enable(null, state));
        hook[0].join(2000L);
        require(!hook[0].isAlive(), "Shutdown recovery thread did not finish");
        array(fake.values.get(7), 1);
        require(fake.writes.size() == 2, "Recovery writers raced or duplicated an override");
        require(output.toString("UTF-8").contains("RECOVERY VERIFIED"), "Recovery not verified");
    }

    // Implementations deliberately non-public: reflection must use public interfaces,
    // not reflect on getClass() of the hidden Binder proxy implementation.
    static final class SubService implements ISub, IBinder {
        public int getDefaultDataSubId() { return 7; }
        public int getSubId(int slot) { return slot == 0 ? 7 : 8; }
        public int getSlotIndex(int sub) { return sub == 7 ? 0 : sub == 8 ? 1 : -1; }
    }

    static final class LoaderService implements ICarrierConfigLoader, IBinder {
        final PersistableBundle merged = new PersistableBundle();
        int calls;
        LoaderService() { merged.putIntArray(NrSaPolicy.KEY, new int[] {1}); merged.putIntArray(OTHER, new int[] {91}); }
        public PersistableBundle getConfigForSubIdWithFeature(int sub, String pkg, String feature) {
            require(sub == 7 && pkg == null && feature == null, "Unexpected root read arguments");
            return merged;
        }
        public void overrideConfig(int sub, PersistableBundle bundle, boolean persistent) {
            require(sub == 7, "Wrong Binder subscription");
            require(bundle != null && !persistent, "Null/persistent override is forbidden");
            require(bundle.values.size() == 1 && bundle.values.containsKey(NrSaPolicy.KEY),
                "Override copied or cleared unrelated keys");
            merged.values.putAll(bundle.values);
            calls++;
        }
    }

    static void reflectionContract() throws Exception {
        LoaderService loader = new LoaderService();
        ServiceManager.services.put("carrier_config", loader);
        ServiceManager.services.put("isub", new SubService());
        NrSaPolicy.ReflectionBackend backend = new NrSaPolicy.ReflectionBackend();
        NrSaPolicy.Identity identity = backend.identity(null);
        require(identity.slot == 0 && identity.sub == 7, "Wrong reflected identity");
        array(backend.read(7), 1);
        backend.override(7, new int[] {1, 2});
        array(backend.read(7), 1, 2);
        array(loader.merged.getIntArray(OTHER), 91);
        backend.override(7, new int[] {1});
        array(loader.merged.getIntArray(OTHER), 91);
        require(loader.calls == 2, "Unexpected Binder write count");
        android.os.Process.uid = 1000;
        fails(() -> new NrSaPolicy.ReflectionBackend());
    }

    public static void main(String[] args) throws Exception {
        require(args.length == 2, "Usage: CASE STATE_DIR");
        state = Paths.get(args[1]);
        switch (args[0]) {
            case "status": status(); break;
            case "noop": noop(); break;
            case "enable": enable(); break;
            case "asynchronous": asynchronous(); break;
            case "unsupported": unsupported(); break;
            case "switchedBeforeWrite": switchedBeforeWrite(); break;
            case "changedBeforeWrite": changedBeforeWrite(); break;
            case "restore": restore(); break;
            case "restoreBinding": restoreBinding(); break;
            case "restoreChangedTarget": restoreChangedTarget(); break;
            case "malformedBackup": malformedBackup(); break;
            case "appliedThenThrow": appliedThenThrow(); break;
            case "queuedThenThrow": queuedThenThrow(); break;
            case "denied": denied(); break;
            case "boundedTimeout": boundedTimeout(); break;
            case "switchedAfterApply": switchedAfterApply(); break;
            case "shutdownRequest": shutdownRequest(); break;
            case "reflectionContract": reflectionContract(); break;
            default: throw new AssertionError("Unknown case");
        }
        System.out.println("PASS " + args[0]);
    }
}
