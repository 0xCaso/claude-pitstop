"""Per-session state: one small JSON file per session id, read and written under a lock."""
import contextlib
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from pitstop.core.fsutil import atomic_write_text, file_lock
from pitstop.core.paths import Layout

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_FIELDS = ("excluded", "requested_at_tokens", "last_transcript_size", "last_context_tokens",
           "awaiting_resume_base", "last_error")


@dataclass
class SessionState:
    session_id: str
    excluded: bool = False
    requested_at_tokens: Optional[int] = None
    last_transcript_size: int = -1
    last_context_tokens: Optional[int] = None
    awaiting_resume_base: bool = False
    last_error: Optional[str] = None


def is_safe_session_id(session_id: str) -> bool:
    return bool(_SAFE_ID.match(session_id))


def session_key(session_id: str) -> str:
    """File-name-safe key for a session id."""
    if is_safe_session_id(session_id):
        return session_id
    return "h-" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


def _path(layout: Layout, session_id: str) -> Path:
    return layout.state_dir / (session_key(session_id) + ".json")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid(raw: Dict[str, Any]) -> bool:
    return (
        isinstance(raw.get("excluded", False), bool)
        and isinstance(raw.get("awaiting_resume_base", False), bool)
        and (raw.get("requested_at_tokens") is None or _is_int(raw.get("requested_at_tokens")))
        and (raw.get("last_context_tokens") is None or _is_int(raw.get("last_context_tokens")))
        and _is_int(raw.get("last_transcript_size", -1))
        and (raw.get("last_error") is None or isinstance(raw.get("last_error"), str))
    )


def load_state(layout: Layout, session_id: str) -> SessionState:
    """Missing, corrupt or wrongly typed state starts fresh: state is a cache, never a reason to fail."""
    try:
        raw = json.loads(_path(layout, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return SessionState(session_id=session_id)
    if not isinstance(raw, dict) or not _valid(raw):
        return SessionState(session_id=session_id)
    state = SessionState(session_id=session_id)
    for key in _FIELDS:
        if key in raw:
            setattr(state, key, raw[key])
    return state


def save_state(layout: Layout, state: SessionState) -> None:
    atomic_write_text(_path(layout, state.session_id), json.dumps(asdict(state), indent=2) + "\n")


@contextlib.contextmanager
def locked_state(layout: Layout, session_id: str, timeout: float = 2.0) -> Iterator[SessionState]:
    """Load under the session lock and save on normal exit, `return` included.
    An exception inside the block discards the changes."""
    path = _path(layout, session_id)
    with file_lock(path.with_suffix(".lock"), timeout=timeout):
        state = load_state(layout, session_id)
        yield state
        save_state(layout, state)
