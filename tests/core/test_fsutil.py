import os
import stat
import time

from pitstop.core.fsutil import LockTimeout, append_line, atomic_write_text, ensure_dir, file_lock
from tests.helpers import TempLayoutTestCase


class AtomicWriteTest(TempLayoutTestCase):
    def test_writes_content_with_private_permissions(self):
        target = self.tmp / "a" / "b.json"
        atomic_write_text(target, "hello")
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_replaces_existing_file_and_leaves_no_temp_files(self):
        target = self.tmp / "c.json"
        atomic_write_text(target, "one")
        atomic_write_text(target, "two")
        self.assertEqual(target.read_text(encoding="utf-8"), "two")
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.name != "pitstop"], ["c.json"])

    def test_ensure_dir_is_private(self):
        path = ensure_dir(self.tmp / "private")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)


class AppendLineTest(TempLayoutTestCase):
    def test_appends_lines_to_private_file(self):
        target = self.tmp / "x" / "log.jsonl"
        append_line(target, "one")
        append_line(target, "due 🔋")
        self.assertEqual(target.read_text(encoding="utf-8"), "one\ndue 🔋\n")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


class FileLockTest(TempLayoutTestCase):
    def test_concurrent_holder_times_out(self):
        lock = self.tmp / "x.lock"
        with file_lock(lock):
            with self.assertRaises(LockTimeout):
                with file_lock(lock, timeout=0.05):
                    pass

    def test_lock_is_free_after_release(self):
        lock = self.tmp / "x.lock"
        with file_lock(lock):
            pass
        with file_lock(lock, timeout=0.05):
            pass

    def test_leftover_lock_file_does_not_block(self):
        lock = self.tmp / "stale.lock"
        lock.write_text("left by a crashed process", encoding="utf-8")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        with file_lock(lock, timeout=0.05):
            pass
