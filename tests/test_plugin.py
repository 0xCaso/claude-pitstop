import json
import unittest

from pitstop.claude.hooks import CLI_PATH, SKILL_PATH
from tests.helpers import REPO_ROOT


class PluginFilesTest(unittest.TestCase):
    def test_manifest(self):
        manifest = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["name"], manifest["author"]["name"]), ("pitstop", "Matteo Casonato"))
        self.assertNotIn("skills", manifest)

    def test_hooks_call_bin_pitstop_with_system_python(self):
        hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), {"Stop", "PostToolBatch", "UserPromptSubmit", "SessionStart"})
        self.assertEqual(hooks["SessionStart"][0]["matcher"], "compact")
        for event, arg in (("Stop", "stop"), ("PostToolBatch", "post-tool-batch"),
                           ("UserPromptSubmit", "user-prompt-submit"), ("SessionStart", "session-start")):
            with self.subTest(event=event):
                command = hooks[event][0]["hooks"][0]["command"]
                self.assertEqual(command, '/usr/bin/python3 "${CLAUDE_PLUGIN_ROOT}/bin/pitstop" hook ' + arg)

    def test_skill_has_frontmatter_sections_and_fixed_lines(self):
        text = SKILL_PATH.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\nname: pitstop\n"))
        for needle in ("## Commands", "## Automatic pitstop", "## Manual pitstop", "## Checkpoint procedure",
                       "## Checkpoint content", "## Resuming", "🔋 **pitstop** · saltato:",
                       "Scrivi /clear", "ripartenza: compact", "t3_thread_send", "Compact context",
                       "/usr/bin/python3 ~/.claude/skills/pitstop/bin/pitstop"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_paths_used_by_hooks_exist(self):
        self.assertTrue(CLI_PATH.is_file())
        self.assertTrue(SKILL_PATH.is_file())
