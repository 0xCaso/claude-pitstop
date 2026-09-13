import json
from unittest import mock

from pitstop.claude.hooks import run_hook
from pitstop.core.config import update_config
from pitstop.core.fsutil import LockTimeout
from pitstop.core.log import read_events
from pitstop.core.state import locked_state
from pitstop.core.store import PendingRecord, mark_pending
from tests.helpers import NOW, TempLayoutTestCase, assistant_line, user_line, write_jsonl

EVENT_NAMES = {"stop": "Stop", "post-tool-batch": "PostToolBatch", "user-prompt-submit": "UserPromptSubmit"}


class HookTestCase(TempLayoutTestCase):
    def setUp(self):
        super().setUp()
        self.notes = []
        self.transcript = write_jsonl(self.tmp / "session.jsonl", [user_line()])

    def notifier(self, title, message):
        self.notes.append((title, message))

    def add_turn(self, tokens, path=None):
        """Append an assistant message: the transcript grows, as in a real session."""
        line = assistant_line(message_id="m%d" % tokens, input_tokens=tokens, cache_read=0, cache_creation=0)
        target = path or self.transcript
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")

    def call_hook(self, event_arg, now=NOW, notifier=None, **overrides):
        data = {"hook_event_name": EVENT_NAMES[event_arg], "session_id": "s1",
                "transcript_path": str(self.transcript), "cwd": "/work/repo"}
        data.update(overrides)
        out = run_hook(event_arg, json.dumps(data), self.layout, notifier=notifier or self.notifier, now=now)
        return json.loads(out) if out else None

    def errors(self):
        return [e["error"] for e in read_events(self.layout) if e["action"] == "error"]


class StopHookTest(HookTestCase):
    def test_below_threshold_is_silent(self):
        self.add_turn(199999)
        self.assertIsNone(self.call_hook("stop"))
        self.assertEqual(read_events(self.layout), [])

    def test_over_threshold_requests_once_per_step(self):
        self.add_turn(212345)
        out = self.call_hook("stop")
        self.assertEqual(out["systemMessage"], "🔋 pitstop · 212K → ai box al prossimo punto pulito")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "Stop")
        context = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("mode: conversation", context)
        self.assertIn("cwd: /work/repo", context)
        self.assertIn("/bin/pitstop", context)
        self.assertEqual(self.notes, [("pitstop", "Ai box a 212K: checkpoint al prossimo punto pulito")])
        self.assertIsNone(self.call_hook("stop"))
        self.add_turn(262345)
        self.assertIsNotNone(self.call_hook("stop"))
        self.assertEqual([e["action"] for e in read_events(self.layout)], ["request", "request"])

    def test_stop_hook_active_and_subagents_are_ignored(self):
        self.add_turn(300000)
        self.assertIsNone(self.call_hook("stop", stop_hook_active=True))
        self.assertIsNone(self.call_hook("stop", agent_id="ag1"))

    def test_disabled_or_excluded_is_silent(self):
        self.add_turn(300000)
        update_config(self.layout, enabled=False)
        self.assertIsNone(self.call_hook("stop"))
        update_config(self.layout, enabled=True)
        with locked_state(self.layout, "s1") as state:
            state.excluded = True
        self.assertIsNone(self.call_hook("stop"))

    def test_notify_off_sends_no_notification(self):
        update_config(self.layout, notify=False)
        self.add_turn(300000)
        self.assertIsNotNone(self.call_hook("stop"))
        self.assertEqual(self.notes, [])

    def test_background_tasks_are_reported(self):
        self.add_turn(300000)
        out = self.call_hook("stop", background_tasks=[{"id": "a"}])
        self.assertIn("background tasks running: 1", out["hookSpecificOutput"]["additionalContext"])

    def test_invalid_config_shows_one_banner(self):
        self.layout.base.mkdir(parents=True, exist_ok=True)
        self.layout.config.write_text('{"threshold_tokens": 1}', encoding="utf-8")
        self.add_turn(300000)
        out = self.call_hook("stop")
        self.assertEqual(set(out), {"systemMessage"})
        self.assertIn("config.json non valido", out["systemMessage"])
        self.assertIsNone(self.call_hook("stop"))


class PostToolBatchHookTest(HookTestCase):
    def test_requests_at_next_boundary_and_shares_state_with_stop(self):
        self.add_turn(212345)
        out = self.call_hook("post-tool-batch", tool_calls=[])
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PostToolBatch")
        self.assertIn("clean boundary", out["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.call_hook("stop"))

    def test_unchanged_transcript_is_not_read_again(self):
        self.add_turn(100000)
        self.assertIsNone(self.call_hook("post-tool-batch"))
        with mock.patch("pitstop.claude.hooks.read_context_tokens") as reader:
            self.assertIsNone(self.call_hook("post-tool-batch"))
            reader.assert_not_called()
        self.add_turn(212345)
        self.assertIsNotNone(self.call_hook("post-tool-batch"))


class ResumeHookTest(HookTestCase):
    def pending(self, **overrides):
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint\nprossima azione: X", encoding="utf-8")
        values = dict(checkpoint=str(checkpoint), session_id="s1", cwd="/work/repo", context_tokens=212000,
                      created_at=NOW - 60, title="Titolo", plan=None)
        values.update(overrides)
        mark_pending(self.layout, PendingRecord(**values))

    def test_resume_injects_checkpoint_once(self):
        self.pending()
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh))
        specific = out["hookSpecificOutput"]
        self.assertEqual(out["systemMessage"], "🔋 pitstop · ripartito da 212K")
        self.assertIn("prossima azione: X", specific["additionalContext"])
        self.assertEqual(specific["hookEventName"], "UserPromptSubmit")
        self.assertNotIn("initialUserMessage", specific)
        self.assertEqual(specific["sessionTitle"], "🔋 Titolo")
        self.assertEqual(self.notes, [("pitstop", "Ripartito da 212K")])
        self.assertIsNone(self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh)))
        self.assertEqual([e["action"] for e in read_events(self.layout)], ["resume"])

    def test_other_cwd_does_not_resume(self):
        self.pending()
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        self.assertIsNone(
            self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh), cwd="/work/other")
        )

    def test_badged_title_is_not_badged_twice(self):
        self.pending(title="🔋 Già marcata")
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh))
        self.assertEqual(out["hookSpecificOutput"]["sessionTitle"], "🔋 Già marcata")

    def test_plan_is_named_in_context_and_missing_transcript_counts_as_fresh(self):
        self.pending(plan="docs/superpowers/plans/p.md")
        missing = str(self.tmp / "does-not-exist.jsonl")
        out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=missing)
        self.assertIn("docs/superpowers/plans/p.md", out["hookSpecificOutput"]["additionalContext"])

    def test_session_with_replies_and_expired_records_do_not_resume(self):
        self.pending()
        self.add_turn(100000)  # self.transcript now has a reply: no longer a fresh session
        self.assertIsNone(self.call_hook("user-prompt-submit", session_id="s1", transcript_path=str(self.transcript)))
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        self.assertIsNotNone(self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh)))
        # separately: a fresh prompt outside the resume window does not resume either
        self.pending()
        fresh2 = write_jsonl(self.tmp / "s3.jsonl", [user_line()])
        self.assertIsNone(
            self.call_hook("user-prompt-submit", session_id="s3", transcript_path=str(fresh2), now=NOW + 3600)
        )

    def test_resume_works_even_when_disabled(self):
        self.pending()
        update_config(self.layout, enabled=False)
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        self.assertIsNotNone(self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh)))

    def test_missing_checkpoint_file_gives_failure_banner(self):
        self.pending(checkpoint=str(self.tmp / "gone.md"))
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh))
        self.assertEqual(out, {"systemMessage": "🔋 pitstop · checkpoint non trovato, riparto senza"})
        self.assertEqual(self.errors(), ["checkpoint_missing"])

    def test_resume_starts_a_new_segment_and_logs_resume_base(self):
        self.add_turn(212345)
        self.assertIsNotNone(self.call_hook("stop"))
        self.pending()
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        self.assertIsNotNone(self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh)))
        self.add_turn(74000, path=fresh)
        self.assertIsNone(self.call_hook("stop", session_id="s2", transcript_path=str(fresh)))
        self.add_turn(205000, path=fresh)
        self.assertIsNotNone(self.call_hook("stop", session_id="s2", transcript_path=str(fresh)))
        bases = [e["resume_base"] for e in read_events(self.layout) if e["action"] == "resume_base"]
        self.assertEqual(bases, [74000])

    def test_resume_base_is_logged_by_post_tool_batch_when_it_sees_tokens_first(self):
        self.add_turn(212345)
        self.assertIsNotNone(self.call_hook("stop"))
        self.pending()
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        self.assertIsNotNone(self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh)))
        self.add_turn(74000, path=fresh)
        self.assertIsNone(
            self.call_hook("post-tool-batch", session_id="s2", transcript_path=str(fresh), tool_calls=[])
        )
        self.assertIsNone(self.call_hook("stop", session_id="s2", transcript_path=str(fresh)))
        base_events = [e for e in read_events(self.layout) if e["action"] == "resume_base"]
        self.assertEqual(len(base_events), 1)
        self.assertEqual((base_events[0]["event"], base_events[0]["resume_base"]), ("post_tool_batch", 74000))

    def test_resume_survives_cwd_drift_when_project_dir_matches(self):
        # The session did `cd web` before the pitstop: the record's cwd is the subfolder, but its
        # project_dir (the original transcript's folder) is the same folder the fresh session's
        # transcript lives in, even though the fresh session's own cwd is back at the repo root.
        self.pending(cwd="/work/repo/web", project_dir=str(self.tmp))
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh), cwd="/work/repo")
        self.assertIsNotNone(out)

    def test_state_reset_failure_after_consume_still_returns_resume_output(self):
        self.pending()
        fresh = write_jsonl(self.tmp / "s2.jsonl", [user_line()])
        with mock.patch("pitstop.claude.hooks.locked_state", side_effect=LockTimeout("boom")):
            out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(fresh))
        self.assertEqual(out["systemMessage"], "🔋 pitstop · ripartito da 212K")
        self.assertEqual(self.errors(), ["lock_timeout"])

    def test_no_pending_records_skips_the_transcript_read(self):
        with mock.patch("pitstop.claude.hooks.read_context_tokens") as reader:
            out = self.call_hook("user-prompt-submit", session_id="s2", transcript_path=str(self.tmp / "nope.jsonl"))
        self.assertIsNone(out)
        reader.assert_not_called()


class FailOpenTest(HookTestCase):
    def test_bad_input_unknown_event_and_missing_transcript_fail_open(self):
        self.assertIsNone(run_hook("stop", "not json", self.layout, notifier=self.notifier))
        self.assertIsNone(run_hook("bogus", "{}", self.layout, notifier=self.notifier))
        missing = str(self.tmp / "missing.jsonl")
        self.assertIsNone(self.call_hook("stop", transcript_path=missing))
        self.assertIsNone(self.call_hook("post-tool-batch", transcript_path=missing))
        self.assertIsNone(self.call_hook("post-tool-batch", transcript_path=missing))
        self.assertEqual(self.errors(), ["input_error", "unknown_event", "fs_error"])

    def test_schema_error_is_logged_once_per_session(self):
        bad = assistant_line()
        bad["message"]["usage"] = []
        write_jsonl(self.transcript, [bad])
        self.assertIsNone(self.call_hook("stop"))
        self.assertIsNone(self.call_hook("stop"))
        self.assertIsNone(self.call_hook("post-tool-batch"))
        self.assertEqual(self.errors(), ["schema_error"])

    def test_unwritable_home_fails_open(self):
        self.layout.base.write_text("not a directory", encoding="utf-8")
        self.add_turn(300000)
        self.assertIsNone(self.call_hook("stop"))

    def test_notifier_failure_does_not_lose_the_request(self):
        def broken(title, message):
            raise RuntimeError("boom")
        self.add_turn(300000)
        self.assertIsNotNone(self.call_hook("stop", notifier=broken))
