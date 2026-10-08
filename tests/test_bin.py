import json
import os
import subprocess

from pitstop.core.config import update_config
from tests.helpers import REPO_ROOT, TempLayoutTestCase, assistant_line, write_jsonl


class BinHookTest(TempLayoutTestCase):
    def run_bin(self, stdin_bytes):
        env = dict(os.environ, PITSTOP_HOME=str(self.layout.base))
        return subprocess.run(["/usr/bin/python3", str(REPO_ROOT / "bin" / "pitstop"), "hook", "stop"],
                              input=stdin_bytes, capture_output=True, env=env, timeout=10)

    def test_hook_runs_with_system_python(self):
        update_config(self.layout, notify=False)
        transcript = write_jsonl(self.tmp / "s.jsonl", [assistant_line()])
        payload = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": str(transcript), "cwd": "/work/repo"}
        result = self.run_bin(json.dumps(payload).encode("utf-8"))
        self.assertEqual((result.returncode, result.stderr), (0, b""))
        self.assertEqual(json.loads(result.stdout)["systemMessage"], "🔋 pitstop · 212K → pitting at the next clean point")

    def test_garbage_input_exits_zero_silently(self):
        result = self.run_bin(b"garbage")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b"", b""))
