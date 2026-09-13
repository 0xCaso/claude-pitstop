"""Checkpoint files and pending-resume records."""
import contextlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from pitstop.core.fsutil import atomic_write_text, ensure_dir
from pitstop.core.paths import Layout
from pitstop.core.state import session_key


@dataclass(frozen=True)
class PendingRecord:
    checkpoint: str
    session_id: str
    cwd: str
    context_tokens: int
    created_at: float
    title: Optional[str] = None
    plan: Optional[str] = None
    project_dir: Optional[str] = None


def new_checkpoint_path(layout: Layout, session_id: str, now: float) -> Path:
    ensure_dir(layout.base)
    ensure_dir(layout.checkpoints_dir)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return layout.checkpoints_dir / ("%s-%s.md" % (stamp, session_key(session_id)[:8]))


def write_checkpoint(layout: Layout, session_id: str, text: str, now: float) -> Path:
    path = new_checkpoint_path(layout, session_id, now)
    atomic_write_text(path, text)
    return path


def mark_pending(layout: Layout, record: PendingRecord) -> Path:
    ensure_dir(layout.base)
    ensure_dir(layout.pending_dir)
    name = "%013d-%s.json" % (int(record.created_at * 1000), uuid.uuid4().hex[:8])
    path = layout.pending_dir / name
    atomic_write_text(path, json.dumps(asdict(record), ensure_ascii=False, indent=2) + "\n")
    return path


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_record_name(path: Path) -> bool:
    """A visible pending-record file: not a mkstemp temp name or a claimed-but-not-yet-unlinked one."""
    return path.suffix == ".json" and not path.name.startswith(".")


def _read_record(path: Path) -> Optional[PendingRecord]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        record = PendingRecord(**raw)
    except (OSError, ValueError, TypeError):
        return None
    valid = (
        isinstance(record.checkpoint, str)
        and isinstance(record.session_id, str)
        and isinstance(record.cwd, str)
        and isinstance(record.context_tokens, int) and not isinstance(record.context_tokens, bool)
        and _is_number(record.created_at)
        and (record.title is None or isinstance(record.title, str))
        and (record.plan is None or isinstance(record.plan, str))
        and (record.project_dir is None or isinstance(record.project_dir, str))
    )
    return record if valid else None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def has_pending(layout: Layout) -> bool:
    """True if pending/ holds at least one visible record file (a cheap check before reading
    anything else: callers use it to skip work entirely when nothing is pending)."""
    try:
        return any(_is_record_name(p) for p in layout.pending_dir.iterdir())
    except FileNotFoundError:
        return False


def consume_pending(layout: Layout, session_id: str, cwd: str, now: float, window_minutes: int,
                    project_dir: Optional[str] = None) -> Optional[PendingRecord]:
    """Take the record for a session that has just been cleared.

    Same session id first; then the newest record from the same project folder (the parent
    directory of the session's transcript file, which stays put even if the session's cwd moved
    mid-run via `cd`); then, as a fallback for records with no project_dir, the newest record from
    the same cwd. Records older than the window expire and are deleted. Consuming is an atomic
    rename, so a record resumes at most one session."""
    try:
        paths = sorted((p for p in layout.pending_dir.iterdir() if _is_record_name(p)), reverse=True)
    except FileNotFoundError:
        return None
    window = window_minutes * 60
    same_id: List[Tuple[Path, PendingRecord]] = []
    same_project: List[Tuple[Path, PendingRecord]] = []
    same_cwd: List[Tuple[Path, PendingRecord]] = []
    for path in paths:
        record = _read_record(path)
        created = record.created_at if record is not None else _mtime(path)
        if now - created > window:
            with contextlib.suppress(OSError):
                path.unlink()
            continue
        if record is None:
            continue
        if record.session_id == session_id:
            same_id.append((path, record))
        elif (record.project_dir is not None and project_dir is not None
              and os.path.realpath(record.project_dir) == os.path.realpath(project_dir)):
            same_project.append((path, record))
        elif os.path.realpath(record.cwd) == os.path.realpath(cwd):
            same_cwd.append((path, record))
    for path, record in same_id + same_project + same_cwd:
        claimed = path.with_name(".%s.claimed-%s" % (path.name, uuid.uuid4().hex[:8]))
        try:
            os.rename(str(path), str(claimed))
        except FileNotFoundError:
            continue
        with contextlib.suppress(OSError):
            claimed.unlink()
        return record
    return None
