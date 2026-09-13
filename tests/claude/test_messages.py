import dataclasses
import unittest

from pitstop.claude.messages import (
    badge_title,
    banner_resumed,
    banner_triggered,
    batch_request_context,
    done_line,
    resume_context,
    resumed_line,
    stop_request_context,
)
from pitstop.core.store import PendingRecord

RECORD = PendingRecord(checkpoint="/cp/20260913-101010-s1.md", session_id="s1", cwd="/work/repo",
                       context_tokens=212000, created_at=1.0, title="Titolo")


class MessagesTest(unittest.TestCase):
    def test_fixed_formats(self):
        self.assertEqual(banner_triggered(212345), "🔋 pitstop · 212K → ai box al prossimo punto pulito")
        self.assertEqual(banner_resumed(212999), "🔋 pitstop · ripartito da 212K")
        self.assertEqual(done_line(212000), "🔋 **pitstop** · fatto a 212K → rientro in pista pulito")
        self.assertEqual(resumed_line(212000), "🔋 **pitstop** · ripartito da 212K · Dove eravamo:")

    def test_badge_title_has_no_double_prefix(self):
        self.assertEqual(badge_title("Piano pitstop"), "🔋 Piano pitstop")
        self.assertEqual(badge_title("🔋 Piano pitstop"), "🔋 Piano pitstop")
        self.assertIsNone(badge_title(None))
        self.assertIsNone(badge_title("  "))

    def test_resume_context_names_the_plan_only_when_set(self):
        self.assertNotIn("subagent-driven-development", resume_context(RECORD, "# C", cli="/c"))
        with_plan = dataclasses.replace(RECORD, plan="docs/superpowers/plans/p.md")
        self.assertIn(
            "resume the plan `docs/superpowers/plans/p.md` from its ledger with superpowers:subagent-driven-development",
            resume_context(with_plan, "# C", cli="/c"),
        )

    def test_request_contexts_carry_the_values_the_skill_needs(self):
        for builder in (stop_request_context, batch_request_context):
            with self.subTest(builder=builder.__name__):
                text = builder(tokens=212345, threshold=200000, step=50000, cwd="/work/repo", cli="/repo/bin/pitstop",
                               skill="/repo/skills/pitstop/SKILL.md", background_tasks=None)
                for expected in ("[pitstop]", "212K", "cwd: /work/repo", "/usr/bin/python3 /repo/bin/pitstop",
                                 "/repo/skills/pitstop/SKILL.md", "Automatic pitstop", "+50000"):
                    self.assertIn(expected, text)

    def test_modes_and_background_tasks(self):
        stop_text = stop_request_context(212345, 200000, 50000, "/w", "/c", "/s", 2)
        batch_text = batch_request_context(212345, 200000, 50000, "/w", "/c", "/s", None)
        self.assertIn("mode: conversation", stop_text)
        self.assertIn("background tasks running: 2", stop_text)
        self.assertIn("clean boundary", batch_text)
        self.assertIn("background tasks running: unknown", batch_text)

    def test_resume_context_embeds_checkpoint_and_resumed_line(self):
        text = resume_context(RECORD, "# Checkpoint\nobiettivo {non un placeholder}", cli="/repo/bin/pitstop")
        self.assertIn("# Checkpoint\nobiettivo {non un placeholder}", text)
        self.assertIn(RECORD.checkpoint, text)
        self.assertIn("🔋 **pitstop** · ripartito da 212K · Dove eravamo:", text)
        self.assertIn('/usr/bin/python3 /repo/bin/pitstop gap "', text)
