import stat
from unittest.mock import patch

from pitstop.core.store import (
    EXPIRED_NOTICE_HORIZON_SECONDS,
    PendingRecord,
    consume_expired_pending,
    consume_pending,
    has_pending,
    mark_pending,
    new_checkpoint_path,
    write_checkpoint,
)
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
    def consume(self, session_id="s-old", cwd="/work/repo", now=NOW, window=10, project_dir=None):
        return consume_pending(self.layout, session_id, cwd, now, window, project_dir=project_dir)

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

    def test_expired_record_within_notice_horizon_is_not_consumed_but_kept(self):
        # Past the window (600s) but still inside the 24h notice horizon: consume_pending must not
        # resume it, but it also must not delete it — consume_expired_pending needs it to still be
        # there to build the "checkpoint scaduto" notice.
        mark_pending(self.layout, record(created_at=NOW - 601))
        self.assertIsNone(self.consume())
        self.assertEqual(len(list(self.layout.pending_dir.iterdir())), 1)

    def test_expired_record_past_the_notice_horizon_is_deleted_not_consumed(self):
        mark_pending(self.layout, record(created_at=NOW - EXPIRED_NOTICE_HORIZON_SECONDS - 1))
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

    def test_cwd_moved_but_project_dir_matches_is_consumed(self):
        # The session did `cd web` mid-run: the checkpoint's cwd is the subfolder, but the fresh
        # session's project folder (its transcript's parent) is still the same as the record's.
        mark_pending(self.layout, record(cwd="/work/repo/web", project_dir="/proj/p1"))
        self.assertIsNotNone(self.consume(session_id="s-new", cwd="/work/repo", project_dir="/proj/p1"))

    def test_different_project_dir_and_cwd_is_not_consumed(self):
        mark_pending(self.layout, record(cwd="/work/repo", project_dir="/proj/p1"))
        self.assertIsNone(self.consume(session_id="s-new", cwd="/work/other", project_dir="/proj/p2"))

    def test_record_without_project_dir_still_resumes_on_cwd_equality(self):
        mark_pending(self.layout, record(cwd="/work/repo"))  # no project_dir override: stays None
        self.assertIsNotNone(self.consume(session_id="s-new", cwd="/work/repo", project_dir="/proj/other"))


class ConsumeExpiredPendingTest(TempLayoutTestCase):
    """The counterpart to consume_pending used for the "checkpoint scaduto" notice: matches the same
    way a resume would, but only for records past the window and still inside the 24h horizon."""

    def checkpoint(self):
        path = self.tmp / "cp.md"
        path.write_text("# Checkpoint", encoding="utf-8")
        return str(path)

    def consume(self, session_id="s-old", cwd="/work/repo", now=NOW, window=10, project_dir=None):
        return consume_expired_pending(self.layout, session_id, cwd, now, window, project_dir=project_dir)

    def test_no_pending_dir_returns_none(self):
        self.assertIsNone(self.consume())

    def test_expired_matching_record_is_claimed(self):
        cp = self.checkpoint()
        mark_pending(self.layout, record(checkpoint=cp, created_at=NOW - 1800))
        matched = self.consume()
        self.assertEqual(matched, record(checkpoint=cp, created_at=NOW - 1800))
        self.assertEqual(list(self.layout.pending_dir.iterdir()), [])

    def test_still_valid_record_is_left_for_consume_pending(self):
        mark_pending(self.layout, record(checkpoint=self.checkpoint(), created_at=NOW - 60))  # within window
        self.assertIsNone(self.consume())
        self.assertEqual(len(list(self.layout.pending_dir.iterdir())), 1)

    def test_record_past_the_notice_horizon_is_deleted_not_returned(self):
        mark_pending(self.layout, record(checkpoint=self.checkpoint(),
                                          created_at=NOW - EXPIRED_NOTICE_HORIZON_SECONDS - 1))
        self.assertIsNone(self.consume())
        self.assertEqual(list(self.layout.pending_dir.iterdir()), [])

    def test_non_matching_cwd_and_project_is_left_in_place(self):
        mark_pending(self.layout, record(checkpoint=self.checkpoint(), created_at=NOW - 1800, cwd="/work/other"))
        self.assertIsNone(self.consume(session_id="s-new", cwd="/work/repo"))
        self.assertEqual(len(list(self.layout.pending_dir.iterdir())), 1)

    def test_missing_checkpoint_file_is_dropped_silently(self):
        mark_pending(self.layout, record(checkpoint=str(self.tmp / "gone.md"), created_at=NOW - 1800))
        self.assertIsNone(self.consume())
        self.assertEqual(list(self.layout.pending_dir.iterdir()), [])

    def test_newest_matching_record_wins(self):
        mark_pending(self.layout, record(session_id="a", checkpoint=self.checkpoint(), created_at=NOW - 3600))
        newer = self.tmp / "newer.md"
        newer.write_text("# Newer", encoding="utf-8")
        mark_pending(self.layout, record(session_id="b", checkpoint=str(newer), created_at=NOW - 1800))
        matched = self.consume(session_id="s-new")
        self.assertEqual(matched.checkpoint, str(newer))


class MarkPendingDedupeTest(TempLayoutTestCase):
    def test_newer_checkpoint_replaces_older_one_from_same_session(self):
        mark_pending(self.layout, record(session_id="s1", created_at=NOW - 120, cwd="/work/repo/old",
                                          project_dir="/proj/p1", checkpoint="/tmp/old.md"))
        mark_pending(self.layout, record(session_id="s1", created_at=NOW - 60, cwd="/work/repo/new",
                                          project_dir="/proj/p1", checkpoint="/tmp/new.md"))
        self.assertEqual(len(list(self.layout.pending_dir.iterdir())), 1)

        first = consume_pending(self.layout, "s-fresh", "/work/repo/other", NOW, 10, project_dir="/proj/p1")
        self.assertEqual(first.checkpoint, "/tmp/new.md")

        second = consume_pending(self.layout, "s-fresh", "/work/repo/other", NOW, 10, project_dir="/proj/p1")
        self.assertIsNone(second)

    def test_record_from_other_session_survives(self):
        mark_pending(self.layout, record(session_id="s2", created_at=NOW - 90, cwd="/work/repo/s2dir",
                                          project_dir="/proj/p2", checkpoint="/tmp/s2.md"))
        mark_pending(self.layout, record(session_id="s1", created_at=NOW - 60, cwd="/work/repo/s1dir",
                                          project_dir="/proj/p1", checkpoint="/tmp/s1.md"))
        self.assertEqual(len(list(self.layout.pending_dir.iterdir())), 2)

        survivor = consume_pending(self.layout, "s2", "/work/repo/s2dir", NOW, 10)
        self.assertEqual(survivor.checkpoint, "/tmp/s2.md")

    def test_dedupe_scan_failure_still_returns_the_new_path(self):
        with patch("pathlib.Path.iterdir", side_effect=OSError("boom")):
            path = mark_pending(self.layout, record())
        self.assertTrue(path.exists())
        self.assertEqual(path.parent, self.layout.pending_dir)


class HasPendingTest(TempLayoutTestCase):
    def test_false_when_pending_dir_is_missing(self):
        self.assertFalse(has_pending(self.layout))

    def test_false_when_only_hidden_temp_or_claimed_names_exist(self):
        self.layout.pending_dir.mkdir(parents=True)
        (self.layout.pending_dir / ".tmp-abc123.json").write_text("{}", encoding="utf-8")
        (self.layout.pending_dir / ".9999999999999-a.json.claimed-deadbeef").write_text("{}", encoding="utf-8")
        self.assertFalse(has_pending(self.layout))

    def test_true_after_mark_pending(self):
        mark_pending(self.layout, record())
        self.assertTrue(has_pending(self.layout))
