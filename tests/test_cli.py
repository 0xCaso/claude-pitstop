import io
import json
from pathlib import Path

from pitstop.cli import main
from pitstop.core.config import load_config
from pitstop.core.log import log_event, read_events
from pitstop.core.state import load_state
from pitstop.core.store import consume_pending
from tests.helpers import NOW, TempLayoutTestCase, assistant_line, user_line, write_jsonl

SESSION_ENV = {"CLAUDE_CODE_SESSION_ID": "s1"}


class CliTestCase(TempLayoutTestCase):
    def setUp(self):
        super().setUp()
        self.projects = self.tmp / "projects"
        self.transcript = write_jsonl(self.projects / "-work-repo" / "s1.jsonl", [
            {"type": "custom-title", "customTitle": "Piano pitstop", "sessionId": "s1"},
            user_line(),
            assistant_line(),
        ])

    def cli(self, *argv, stdin_text="", env=None):
        out = io.StringIO()
        code = main(list(argv), stdin=io.StringIO(stdin_text), stdout=out,
                    env=SESSION_ENV if env is None else env, layout=self.layout, projects_dir=self.projects, now=NOW)
        return code, out.getvalue()

    def consume(self):
        return consume_pending(self.layout, "s1", "/work/repo", NOW, 10)


class ToggleCommandsTest(CliTestCase):
    def test_on_off_and_notify_update_config(self):
        self.assertEqual(self.cli("off"), (0, "🔋 pitstop off in all sessions\n"))
        self.assertFalse(load_config(self.layout)[0].enabled)
        self.assertEqual(self.cli("on"), (0, "🔋 pitstop on\n"))
        self.assertTrue(load_config(self.layout)[0].enabled)
        self.assertEqual(self.cli("notify", "off"), (0, "🔋 pitstop notifications off\n"))
        self.assertFalse(load_config(self.layout)[0].notify)

    def test_off_here_excludes_current_session_only(self):
        self.assertEqual(self.cli("off-here"), (0, "🔋 pitstop off in this session\n"))
        self.assertTrue(load_state(self.layout, "s1").excluded)
        self.assertFalse(load_state(self.layout, "s2").excluded)

    def test_session_commands_need_a_session(self):
        code, out = self.cli("off-here", env={})
        self.assertEqual(code, 1)
        self.assertIn("CLAUDE_CODE_SESSION_ID", out)

    def test_invalid_config_is_reported_not_overwritten(self):
        self.layout.base.mkdir(parents=True, exist_ok=True)
        self.layout.config.write_text("{nope", encoding="utf-8")
        code, out = self.cli("on")
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("🔋 pitstop · config.json"))
        self.assertEqual(self.layout.config.read_text(encoding="utf-8"), "{nope")


class MarkPendingTest(CliTestCase):
    def test_new_checkpoint_then_mark_pending_registers_resume(self):
        code, out = self.cli("new-checkpoint")
        self.assertEqual(code, 0)
        path = Path(out.strip())
        path.write_text("# Checkpoint", encoding="utf-8")
        code, out = self.cli("mark-pending", "--checkpoint", str(path), "--cwd", "/work/repo")
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("🔋 **pitstop** · done at 212K → back on track with a clean context\n"))
        record = self.consume()
        self.assertEqual((record.context_tokens, record.title, record.cwd, record.plan),
                         (212010, "Piano pitstop", "/work/repo", None))
        self.assertEqual([e["action"] for e in read_events(self.layout)], ["pitstop_done"])

    def test_restart_mode_follows_the_entrypoint(self):
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint", encoding="utf-8")
        for entrypoint, mode in (("sdk-ts", "compact"), ("sdk-py", "compact"), ("cli", "clear"), (None, "clear")):
            with self.subTest(entrypoint=entrypoint):
                env = dict(SESSION_ENV)
                if entrypoint is not None:
                    env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
                code, out = self.cli("mark-pending", "--checkpoint", str(checkpoint), env=env)
                self.assertEqual(code, 0)
                self.assertIn("restart: %s\n" % mode, out)

    def test_restart_is_automatic_where_the_hooks_module_is_loaded(self):
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint", encoding="utf-8")
        for entrypoint, mode in (("cli", "auto"), (None, "auto"), ("sdk-cli", "auto")):
            with self.subTest(entrypoint=entrypoint):
                env = dict(SESSION_ENV, PITSTOP_AUTO_RESTART="1")
                if entrypoint is not None:
                    env["CLAUDE_CODE_ENTRYPOINT"] = entrypoint
                code, out = self.cli("mark-pending", "--checkpoint", str(checkpoint), env=env)
                self.assertEqual(code, 0)
                self.assertIn("restart: %s\n" % mode, out)

    def test_compact_restart_spells_out_both_queued_messages(self):
        # The session follows the skill text it loaded first, so a later SKILL.md never reaches it: on
        # 8 Oct 2026 a pitstop queued the /compact but not the resume message (issue #1). This output is always current.
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint", encoding="utf-8")
        env = dict(SESSION_ENV, CLAUDE_CODE_ENTRYPOINT="sdk-ts")
        out = self.cli("mark-pending", "--checkpoint", str(checkpoint), env=env)[1]
        self.assertIn('queue 1: /compact One-line summary: "Resume from the pitstop checkpoint."\n', out)
        self.assertIn("queue 2: Resume from the pitstop checkpoint.\n", out)
        self.assertLess(out.index("queue 1:"), out.index("queue 2:"))
        out = self.cli("mark-pending", "--checkpoint", str(checkpoint), env=dict(SESSION_ENV))[1]
        self.assertNotIn("queue ", out)

    def test_cwd_defaults_to_transcript_and_plan_is_kept(self):
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint", encoding="utf-8")
        self.assertEqual(self.cli("mark-pending", "--checkpoint", str(checkpoint), "--plan", "docs/p.md")[0], 0)
        record = self.consume()
        self.assertEqual((record.cwd, record.plan), ("/work/repo", "docs/p.md"))

    def test_stdin_writes_the_checkpoint_itself(self):
        code, _ = self.cli("mark-pending", "--stdin", stdin_text="# Checkpoint da stdin\n")
        self.assertEqual(code, 0)
        record = self.consume()
        self.assertEqual(Path(record.checkpoint).read_text(encoding="utf-8"), "# Checkpoint da stdin\n")
        self.assertEqual(Path(record.checkpoint).parent, self.layout.checkpoints_dir.resolve())

    def test_missing_or_empty_checkpoint_fails_without_pending_record(self):
        empty = self.tmp / "empty.md"
        empty.write_text("", encoding="utf-8")
        for argv in (("--checkpoint", str(self.tmp / "missing.md")), ("--checkpoint", str(empty)), ("--stdin",)):
            with self.subTest(argv=argv):
                code, out = self.cli("mark-pending", *argv)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith("🔋 pitstop · "))
        self.assertIsNone(self.consume())

    def test_unreadable_context_fails(self):
        write_jsonl(self.transcript, [user_line()])
        checkpoint = self.tmp / "cp.md"
        checkpoint.write_text("# Checkpoint", encoding="utf-8")
        code, out = self.cli("mark-pending", "--checkpoint", str(checkpoint))
        self.assertEqual(code, 1)
        self.assertIn("context", out)


class StatusAndGapTest(CliTestCase):
    def test_status_shows_state_context_and_pilot_numbers(self):
        log_event(self.layout, "cli", "pitstop_done", session_id="s1", context_tokens=212000)
        log_event(self.layout, "stop", "resume_base", session_id="s1", resume_base=70000)
        log_event(self.layout, "stop", "resume_base", session_id="s1", resume_base=90000)
        self.assertEqual(self.cli("gap", "missing", "the", "ledger"), (0, "🔋 checkpoint gap recorded\n"))
        code, out = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "🔋 pitstop: on",
            "notifications: on",
            "current context: 212K · threshold 200K",
            "pitstops: 1 · real resumes: 2 · gaps: 1",
            "real resume size: last 90K · median 80K",
        ])
        gaps = [json.loads(line) for line in self.layout.gaps.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((gaps[0]["session_id"], gaps[0]["text"]), ("s1", "missing the ledger"))
        self.assertNotIn("ledger", self.layout.log.read_text(encoding="utf-8"))

    def test_status_reports_exclusion_and_missing_context(self):
        self.cli("off-here")
        self.assertIn("🔋 pitstop: off in this session", self.cli("status")[1])
        self.assertIn("current context: not available", self.cli("status", env={})[1])
