"""What pitstop reads from a Claude Code transcript (JSONL): context size, title, cwd."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from pitstop.core.state import is_safe_session_id

BLOCK_SIZE = 64 * 1024
MAX_SCAN_BYTES = 16 * 1024 * 1024
USAGE_KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


class TranscriptSchemaError(Exception):
    """Usage data is present but not in a shape pitstop understands."""


def _lines_from_end(path: str, max_bytes: int) -> Iterator[bytes]:
    """Yield lines from the last one backwards, reading at most max_bytes from the end.
    The last line may still be being written: callers must tolerate a partial line."""
    with open(path, "rb") as fh:
        position = os.fstat(fh.fileno()).st_size
        remainder = b""
        scanned = 0
        while position > 0 and scanned < max_bytes:
            step = min(BLOCK_SIZE, position)
            position -= step
            scanned += step
            fh.seek(position)
            lines = (fh.read(step) + remainder).split(b"\n")
            remainder = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    yield line
        if position == 0 and remainder.strip():
            yield remainder


def _int_field(usage: Dict[str, Any], key: str) -> int:
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TranscriptSchemaError("usage.%s missing or not an integer" % key)
    return value


def read_context_tokens(transcript_path: str, max_bytes: int = MAX_SCAN_BYTES) -> Optional[int]:
    """Context of the last main-thread assistant message: input + cache read + cache creation tokens.

    Streaming writes one line per content block, all with the same message id and usage, so the
    last valid line already is the deduplicated value. Returns None when there is no assistant
    usage yet. Never estimates."""
    for line in _lines_from_end(transcript_path, max_bytes):
        if b'"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain") is True:
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            raise TranscriptSchemaError("assistant entry without a message object")
        if message.get("model") == "<synthetic>":
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            raise TranscriptSchemaError("assistant message without a usage object")
        return sum(_int_field(usage, key) for key in USAGE_KEYS)
    return None


def read_session_title(transcript_path: str) -> Optional[str]:
    """Latest custom title, else latest AI title. Scans the whole file: call it once per pitstop."""
    custom = None
    generated = None
    with open(transcript_path, "rb") as fh:
        for line in fh:
            if b'-title"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "custom-title" and isinstance(entry.get("customTitle"), str):
                custom = entry["customTitle"]
            elif entry.get("type") == "ai-title" and isinstance(entry.get("aiTitle"), str):
                generated = entry["aiTitle"]
    title = (custom or generated or "").strip()
    return title or None


def read_last_cwd(transcript_path: str, max_bytes: int = MAX_SCAN_BYTES) -> Optional[str]:
    for line in _lines_from_end(transcript_path, max_bytes):
        if b'"cwd"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("isSidechain") is not True:
            cwd = entry.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
    return None


def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def find_transcript(session_id: str, projects_dir: Path) -> Optional[Path]:
    """Main transcript of a session: <projects_dir>/<project>/<session_id>.jsonl, newest if several."""
    if not is_safe_session_id(session_id):
        return None
    matches = [p for p in projects_dir.glob("*/%s.jsonl" % session_id) if p.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)
