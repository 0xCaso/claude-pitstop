"""Shared test helpers."""
import json
import tempfile
import unittest
from pathlib import Path

from pitstop.core.paths import Layout

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = 1800000000.0


class TempLayoutTestCase(unittest.TestCase):
    """A fresh temp folder per test, with a pitstop layout inside it (not created yet)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.layout = Layout(self.tmp / "pitstop")

    def tearDown(self) -> None:
        self._tmp.cleanup()


def assistant_line(input_tokens=10, cache_read=150000, cache_creation=62000, message_id="msg_1",
                   sidechain=False, model="claude-opus-5", **extra):
    """A main-thread assistant transcript entry. Defaults add up to 212010 context tokens."""
    entry = {
        "type": "assistant",
        "isSidechain": sidechain,
        "cwd": "/work/repo",
        "sessionId": "s1",
        "message": {
            "id": message_id,
            "model": model,
            "role": "assistant",
            "usage": {
                "input_tokens": input_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "output_tokens": 500,
            },
        },
    }
    entry.update(extra)
    return entry


def user_line(text="ciao"):
    return {"type": "user", "isSidechain": False, "cwd": "/work/repo", "message": {"role": "user", "content": text}}


def write_jsonl(path, entries, trailing=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
        fh.write(trailing)
    return path
