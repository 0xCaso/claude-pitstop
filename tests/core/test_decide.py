import unittest
from pathlib import Path

from pitstop.core.config import Config
from pitstop.core.decide import NOOP, REQUEST, Decision, Event, decide, segment_start
from pitstop.core.state import SessionState


def stop(tokens, **kwargs):
    return Event(kind="stop", context_tokens=tokens, **kwargs)


class DecideTest(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.state = SessionState(session_id="s")

    def test_threshold_boundaries(self):
        for tokens, action in ((199999, NOOP), (200000, REQUEST), (200001, REQUEST)):
            with self.subTest(tokens=tokens):
                self.assertEqual(decide(self.config, self.state, stop(tokens)).action, action)

    def test_below_threshold_reason(self):
        self.assertEqual(decide(self.config, self.state, stop(10)), Decision(NOOP, "below_threshold"))

    def test_one_request_per_segment_until_step(self):
        self.state.requested_at_tokens = 212000
        self.assertEqual(decide(self.config, self.state, stop(261999)), Decision(NOOP, "already_requested"))
        self.assertEqual(decide(self.config, self.state, stop(262000)), Decision(REQUEST, "threshold"))

    def test_post_tool_batch_shares_the_same_rules(self):
        self.state.requested_at_tokens = 212000
        event = Event(kind="post_tool_batch", context_tokens=230000)
        self.assertEqual(decide(self.config, self.state, event).reason, "already_requested")

    def test_guards(self):
        cases = [
            (Config(enabled=False), SessionState("s"), stop(300000), "disabled"),
            (Config(), SessionState("s", excluded=True), stop(300000), "excluded"),
            (Config(), SessionState("s"), stop(300000, is_subagent=True), "subagent"),
            (Config(), SessionState("s"), stop(300000, stop_hook_active=True), "stop_hook_active"),
            (Config(), SessionState("s"), stop(None), "no_usage"),
        ]
        for config, state, event, reason in cases:
            with self.subTest(reason=reason):
                self.assertEqual(decide(config, state, event), Decision(NOOP, reason))

    def test_custom_threshold_and_step(self):
        config = Config(threshold_tokens=60000, retrigger_step_tokens=10000)
        self.assertEqual(decide(config, self.state, stop(60000)).action, REQUEST)
        self.state.requested_at_tokens = 60000
        self.assertEqual(decide(config, self.state, stop(69999)).action, NOOP)
        self.assertEqual(decide(config, self.state, stop(70000)).action, REQUEST)

    def test_context_back_under_the_threshold_starts_a_new_segment(self):
        # A /compact outside pitstop: without the reset the next request would wait until 270K.
        self.state.requested_at_tokens = 220000
        segment_start(self.config, self.state, 230000)
        self.assertEqual(self.state.requested_at_tokens, 220000)
        segment_start(self.config, self.state, None)
        self.assertEqual(self.state.requested_at_tokens, 220000)
        segment_start(self.config, self.state, 50000)
        self.assertIsNone(self.state.requested_at_tokens)
        self.assertEqual(decide(self.config, self.state, stop(200000)), Decision(REQUEST, "threshold"))


class CoreIndependenceTest(unittest.TestCase):
    def test_core_does_not_import_the_claude_adapter(self):
        core = Path(__file__).resolve().parents[2] / "pitstop" / "core"
        for path in sorted(core.glob("*.py")):
            with self.subTest(file=path.name):
                self.assertNotIn("pitstop.claude", path.read_text(encoding="utf-8"))
