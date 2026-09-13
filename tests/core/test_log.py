import stat

from pitstop.core.log import log_event, read_events
from tests.helpers import TempLayoutTestCase


class LogTest(TempLayoutTestCase):
    def test_appends_allowed_fields_and_skips_none(self):
        log_event(self.layout, "stop", "request", session_id="s1", context_tokens=212000, threshold=200000, error=None)
        log_event(self.layout, "cli", "gap", session_id="s1")
        events = read_events(self.layout)
        self.assertEqual([e["action"] for e in events], ["request", "gap"])
        self.assertEqual(events[0]["context_tokens"], 212000)
        self.assertEqual(events[0]["event"], "stop")
        self.assertNotIn("error", events[0])
        self.assertIn("ts", events[0])

    def test_rejects_fields_outside_whitelist(self):
        with self.assertRaises(ValueError):
            log_event(self.layout, "stop", "request", prompt="secret")

    def test_rejects_non_scalar_values(self):
        with self.assertRaises(ValueError):
            log_event(self.layout, "stop", "request", reason={"text": "x"})

    def test_read_events_skips_corrupt_lines_and_missing_file(self):
        self.assertEqual(read_events(self.layout), [])
        log_event(self.layout, "stop", "request")
        with open(self.layout.log, "a", encoding="utf-8") as fh:
            fh.write("{broken\n[]\n")
        self.assertEqual(len(read_events(self.layout)), 1)

    def test_log_file_is_private(self):
        log_event(self.layout, "stop", "request")
        self.assertEqual(stat.S_IMODE(self.layout.log.stat().st_mode), 0o600)
