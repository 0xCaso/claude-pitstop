import stat

from pitstop.core.store import PendingRecord, consume_pending, mark_pending, new_checkpoint_path, write_checkpoint
from tests.helpers import NOW, TempLayoutTestCase


def record(**overrides):
    values = dict(checkpoint="/tmp/cp.md", session_id="s-old", cwd="/work/repo", context_tokens=212000,
                  created_at=NOW - 60, title="Titolo", plan=None)
    values.update(overrides)
    return PendingRecord(**values)


class CheckpointPathTest(TempLayoutTestCase):
    def test_path_is_in_checkpoints_dir_with_timestamp_and_session_prefix(self):
        path = new_checkpoint_path(self.layout, "0123456789abcdef", NOW)
        self.assertEqual(path.parent, self.layout.checkpoints_dir)
        self.assertTrue(path.parent.is_dir())
        self.assertFalse(path.exists())
        self.assertRegex(path.name, r"^\d{8}-\d{6}-01234567\.md$")

    def test_write_checkpoint_writes_private_file(self):
        path = write_checkpoint(self.layout, "abc", "# Checkpoint", NOW)
        self.assertEqual(path.read_text(encoding="utf-8"), "# Checkpoint")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class ConsumePendingTest(TempLayoutTestCase):
    def consume(self, session_id="s-old", cwd="/work/repo", now=NOW, window=10):
        return consume_pending(self.layout, session_id, cwd, now, window)

    def test_no_pending_dir_returns_none(self):
        self.assertIsNone(self.consume())

    def test_same_session_id_is_consumed(self):
        mark_pending(self.layout, record())
        self.assertEqual(self.consume(), record())

    def test_changed_session_id_falls_back_to_same_cwd(self):
        mark_pending(self.layout, record())
        self.assertEqual(self.consume(session_id="s-new"), record())

    def test_changed_session_id_and_other_cwd_is_not_consumed(self):
        mark_pending(self.layout, record())
        self.assertIsNone(self.consume(session_id="s-new", cwd="/work/other"))

    def test_same_session_id_wins_over_newer_same_cwd_record(self):
        mark_pending(self.layout, record(session_id="s-mine", created_at=NOW - 120, checkpoint="/tmp/mine.md"))
        mark_pending(self.layout, record(session_id="s-other", created_at=NOW - 30, checkpoint="/tmp/other.md"))
        self.assertEqual(self.consume(session_id="s-mine").checkpoint, "/tmp/mine.md")

    def test_newest_same_cwd_record_wins(self):
        mark_pending(self.layout, record(session_id="a", created_at=NOW - 120, checkpoint="/tmp/old.md"))
        mark_pending(self.layout, record(session_id="b", created_at=NOW - 30, checkpoint="/tmp/new.md"))
        self.assertEqual(self.consume(session_id="s-new").checkpoint, "/tmp/new.md")

    def test_expired_record_is_deleted_not_consumed(self):
        mark_pending(self.layout, record(created_at=NOW - 601))
        self.assertIsNone(self.consume())
        self.assertEqual(list(self.layout.pending_dir.iterdir()), [])

    def test_window_edge_is_still_valid(self):
        mark_pending(self.layout, record(created_at=NOW - 600))
        self.assertIsNotNone(self.consume())

    def test_record_is_consumed_only_once(self):
        mark_pending(self.layout, record())
        self.assertIsNotNone(self.consume())
        self.assertIsNone(self.consume())
        self.assertEqual(list(self.layout.pending_dir.iterdir()), [])

    def test_corrupt_record_is_ignored(self):
        self.layout.pending_dir.mkdir(parents=True)
        (self.layout.pending_dir / "9999999999999-bad.json").write_text("{broken", encoding="utf-8")
        mark_pending(self.layout, record())
        self.assertEqual(self.consume(), record())

    def test_cwd_comparison_resolves_symlinks(self):
        real = self.tmp / "real"
        real.mkdir()
        link = self.tmp / "link"
        link.symlink_to(real)
        mark_pending(self.layout, record(cwd=str(link)))
        self.assertIsNotNone(self.consume(session_id="s-new", cwd=str(real)))
