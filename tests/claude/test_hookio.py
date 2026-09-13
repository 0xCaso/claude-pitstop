import json
import unittest

from pitstop.claude.hookio import HookInputError, build_output, parse_hook_input


def payload(**overrides):
    data = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": "/t.jsonl", "cwd": "/work/repo"}
    data.update(overrides)
    return json.dumps(data)


class ParseHookInputTest(unittest.TestCase):
    def test_parses_stop_payload(self):
        inp = parse_hook_input(payload(stop_hook_active=True, background_tasks=[{"id": "a"}, {"id": "b"}]))
        self.assertEqual((inp.event, inp.session_id, inp.stop_hook_active, inp.background_tasks), ("Stop", "s1", True, 2))
        self.assertIsNone(inp.agent_id)

    def test_parses_session_start_and_subagent_fields(self):
        inp = parse_hook_input(payload(hook_event_name="SessionStart", source="clear", session_title="Titolo", agent_id="ag1"))
        self.assertEqual((inp.source, inp.session_title, inp.agent_id), ("clear", "Titolo", "ag1"))

    def test_stop_hook_active_must_be_boolean_true(self):
        self.assertFalse(parse_hook_input(payload(stop_hook_active="true")).stop_hook_active)

    def test_rejects_bad_input(self):
        for raw in ("not json", "[]", payload(session_id=""), payload(cwd=None), json.dumps({"hook_event_name": "Stop"})):
            with self.subTest(raw=raw):
                with self.assertRaises(HookInputError):
                    parse_hook_input(raw)


class BuildOutputTest(unittest.TestCase):
    def test_request_output(self):
        out = json.loads(build_output("Stop", system_message="banner", additional_context="ctx"))
        self.assertEqual(out, {"systemMessage": "banner",
                               "hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": "ctx"}})

    def test_session_start_output(self):
        out = json.loads(build_output("SessionStart", system_message="b", additional_context="c",
                                      initial_user_message="m", session_title="🔋 T"))
        self.assertEqual(out["hookSpecificOutput"], {"hookEventName": "SessionStart", "additionalContext": "c",
                                                     "initialUserMessage": "m", "sessionTitle": "🔋 T"})

    def test_banner_only_output_has_no_specific_block(self):
        self.assertEqual(json.loads(build_output("Stop", system_message="b")), {"systemMessage": "b"})

    def test_output_is_ascii_safe(self):
        self.assertTrue(build_output("Stop", system_message="🔋").isascii())
