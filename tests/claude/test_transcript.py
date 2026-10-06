from pathlib import Path

from pitstop.claude.transcript import (
    TranscriptSchemaError,
    default_projects_dir,
    find_transcript,
    read_context_tokens,
    read_last_cwd,
    read_session_title,
)
from tests.helpers import TempLayoutTestCase, assistant_line, user_line, write_jsonl


class ReadContextTokensTest(TempLayoutTestCase):
    def transcript(self, entries, trailing=""):
        return str(write_jsonl(self.tmp / "t.jsonl", entries, trailing))

    def test_sums_input_and_cache_tokens_of_last_assistant_message(self):
        path = self.transcript([assistant_line(message_id="a", cache_read=1000), user_line(), assistant_line(message_id="b")])
        self.assertEqual(read_context_tokens(path), 212010)

    def test_streaming_lines_of_one_message_are_not_summed(self):
        path = self.transcript([assistant_line(message_id="b") for _ in range(4)])
        self.assertEqual(read_context_tokens(path), 212010)

    def test_ignores_sidechain_and_synthetic_messages(self):
        path = self.transcript([
            assistant_line(message_id="main"),
            assistant_line(message_id="sub", cache_read=999999, sidechain=True),
            assistant_line(message_id="syn", input_tokens=0, cache_read=0, cache_creation=0, model="<synthetic>"),
        ])
        self.assertEqual(read_context_tokens(path), 212010)

    def test_partial_last_line_is_skipped(self):
        path = self.transcript([assistant_line()], trailing='{"type":"assistant","message":{"usage":{"input_')
        self.assertEqual(read_context_tokens(path), 212010)

    def test_no_assistant_usage_returns_none(self):
        self.assertIsNone(read_context_tokens(self.transcript([user_line(), user_line()])))

    def test_empty_file_returns_none(self):
        self.assertIsNone(read_context_tokens(self.transcript([])))

    def test_usage_in_unknown_shape_raises_schema_error(self):
        missing_key = assistant_line()
        del missing_key["message"]["usage"]["cache_read_input_tokens"]
        wrong_type = assistant_line()
        wrong_type["message"]["usage"]["input_tokens"] = "10"
        not_an_object = assistant_line()
        not_an_object["message"]["usage"] = []
        for entry in (missing_key, wrong_type, not_an_object):
            with self.subTest(usage=entry["message"]["usage"]):
                with self.assertRaises(TranscriptSchemaError):
                    read_context_tokens(self.transcript([entry]))

    def test_reads_only_the_tail_of_large_files(self):
        filler = [user_line("x" * 1000) for _ in range(300)]
        path = self.transcript([assistant_line(message_id="old")] + filler)
        self.assertIsNone(read_context_tokens(path, max_bytes=64 * 1024))
        self.assertEqual(read_context_tokens(path), 212010)

    def test_finds_message_across_block_boundaries(self):
        filler = [user_line("y" * 700) for _ in range(200)]
        path = self.transcript([user_line(), assistant_line()] + filler)
        self.assertEqual(read_context_tokens(path), 212010)

    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            read_context_tokens(str(self.tmp / "missing.jsonl"))


class TitleCwdAndLookupTest(TempLayoutTestCase):
    def test_custom_title_wins_over_ai_title(self):
        path = write_jsonl(self.tmp / "t.jsonl", [
            {"type": "ai-title", "aiTitle": "Titolo AI"},
            {"type": "custom-title", "customTitle": "Titolo scelto"},
            {"type": "ai-title", "aiTitle": "Titolo AI nuovo"},
        ])
        self.assertEqual(read_session_title(str(path)), "Titolo scelto")

    def test_ai_title_when_no_custom_title(self):
        path = write_jsonl(self.tmp / "t.jsonl", [{"type": "ai-title", "aiTitle": "Titolo AI"}, user_line()])
        self.assertEqual(read_session_title(str(path)), "Titolo AI")

    def test_no_title_returns_none(self):
        self.assertIsNone(read_session_title(str(write_jsonl(self.tmp / "t.jsonl", [user_line()]))))

    def test_last_cwd_skips_sidechain_entries(self):
        path = write_jsonl(self.tmp / "t.jsonl", [user_line(), assistant_line(sidechain=True, cwd="/elsewhere")])
        self.assertEqual(read_last_cwd(str(path)), "/work/repo")

    def test_find_transcript_by_session_id(self):
        projects = self.tmp / "projects"
        target = write_jsonl(projects / "-work-repo" / "abc-123.jsonl", [user_line()])
        write_jsonl(projects / "-work-repo" / "other.jsonl", [user_line()])
        self.assertEqual(find_transcript("abc-123", projects), target)

    def test_projects_dir_follows_the_account_config_dir(self):
        self.assertEqual(default_projects_dir({"CLAUDE_CONFIG_DIR": "/Users/u/.claude-work"}),
                         Path("/Users/u/.claude-work/projects"))
        self.assertEqual(default_projects_dir({}), Path.home() / ".claude" / "projects")
        self.assertEqual(default_projects_dir({"CLAUDE_CONFIG_DIR": ""}), Path.home() / ".claude" / "projects")

    def test_find_transcript_rejects_unsafe_or_unknown_ids(self):
        projects = self.tmp / "projects"
        write_jsonl(projects / "-work-repo" / "abc.jsonl", [user_line()])
        self.assertIsNone(find_transcript("*", projects))
        self.assertIsNone(find_transcript("nope", projects))
