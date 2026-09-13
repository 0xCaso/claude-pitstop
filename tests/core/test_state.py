import json

from pitstop.core.fsutil import LockTimeout
from pitstop.core.state import SessionState, load_state, locked_state, session_key
from tests.helpers import TempLayoutTestCase


class StateTest(TempLayoutTestCase):
    def test_missing_state_is_fresh(self):
        self.assertEqual(load_state(self.layout, "abc"), SessionState(session_id="abc"))

    def test_locked_state_persists_changes(self):
        with locked_state(self.layout, "abc") as state:
            state.requested_at_tokens = 212000
            state.last_error = "schema_error"
        loaded = load_state(self.layout, "abc")
        self.assertEqual((loaded.requested_at_tokens, loaded.last_error), (212000, "schema_error"))

    def test_return_inside_block_still_saves(self):
        def mark():
            with locked_state(self.layout, "abc") as state:
                state.excluded = True
                return "early"
        self.assertEqual(mark(), "early")
        self.assertTrue(load_state(self.layout, "abc").excluded)

    def test_exception_inside_block_discards_changes(self):
        with self.assertRaises(RuntimeError):
            with locked_state(self.layout, "abc") as state:
                state.excluded = True
                raise RuntimeError("boom")
        self.assertFalse(load_state(self.layout, "abc").excluded)

    def test_corrupt_or_wrongly_typed_state_is_fresh(self):
        self.layout.state_dir.mkdir(parents=True)
        contents = ("{broken", "[]", json.dumps({"excluded": "yes"}), json.dumps({"requested_at_tokens": "212000"}),
                    json.dumps({"last_transcript_size": None}))
        for content in contents:
            with self.subTest(content=content):
                (self.layout.state_dir / "abc.json").write_text(content, encoding="utf-8")
                self.assertEqual(load_state(self.layout, "abc"), SessionState(session_id="abc"))

    def test_concurrent_writer_times_out(self):
        with locked_state(self.layout, "abc"):
            with self.assertRaises(LockTimeout):
                with locked_state(self.layout, "abc", timeout=0.05):
                    pass

    def test_unsafe_session_id_maps_to_hashed_file_inside_state_dir(self):
        with locked_state(self.layout, "../../etc/passwd") as state:
            state.excluded = True
        files = [p.name for p in self.layout.state_dir.iterdir() if p.suffix == ".json"]
        self.assertEqual(files, [session_key("../../etc/passwd") + ".json"])
        self.assertTrue(files[0].startswith("h-"))
        self.assertTrue(load_state(self.layout, "../../etc/passwd").excluded)

    def test_safe_session_id_is_used_as_is(self):
        self.assertEqual(session_key("62a933c1-4a7b-402c-9b1a-24feaa839f9f"), "62a933c1-4a7b-402c-9b1a-24feaa839f9f")
