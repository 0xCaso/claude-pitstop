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

# A record past the resume window is not resumed, but it is not deleted right away either: it stays
# around long enough for the fresh session to be told it expired (see consume_expired_pending), up to
# this horizon. Past the horizon it is deleted silently by the sweep, like an expired record always was.
EXPIRED_NOTICE_HORIZON_SECONDS = 24 * 60 * 60


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
    with contextlib.suppress(OSError):
        for other in layout.pending_dir.iterdir():
            if other == path or not _is_record_name(other):
                continue
            existing = _read_record(other)
            if existing is not None and existing.session_id == record.session_id:
                with contextlib.suppress(OSError):
                    other.unlink()
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


def _list_records(layout: Layout) -> List[Path]:
    return sorted((p for p in layout.pending_dir.iterdir() if _is_record_name(p)), reverse=True)


def _sweep(paths: List[Path], now: float, window: float) -> List[Tuple[Path, PendingRecord, float]]:
    """Delete what today's handling always deleted (an unreadable record past the window, or any
    record past the 24h notice horizon) and return the rest as (path, record, age) triples, newest
    first, for the caller to split into "still valid" and "expired but within the notice horizon"."""
    survivors = []
    for path in paths:
        record = _read_record(path)
        if record is None:
            if now - _mtime(path) > window:
                with contextlib.suppress(OSError):
                    path.unlink()
            continue
        age = now - record.created_at
        if age > EXPIRED_NOTICE_HORIZON_SECONDS:
            with contextlib.suppress(OSError):
                path.unlink()
            continue
        survivors.append((path, record, age))
    return survivors


def _match_levels(pairs: List[Tuple[Path, PendingRecord]], session_id: str, cwd: str,
                  project_dir: Optional[str]) -> List[Tuple[Path, PendingRecord]]:
    """Group by match level (same session id, then project folder, then cwd) and concatenate in that
    priority order; each level keeps the newest-first order it was given in."""
    same_id: List[Tuple[Path, PendingRecord]] = []
    same_project: List[Tuple[Path, PendingRecord]] = []
    same_cwd: List[Tuple[Path, PendingRecord]] = []
    for path, record in pairs:
        if record.session_id == session_id:
            same_id.append((path, record))
        elif (record.project_dir is not None and project_dir is not None
              and os.path.realpath(record.project_dir) == os.path.realpath(project_dir)):
            same_project.append((path, record))
        elif os.path.realpath(record.cwd) == os.path.realpath(cwd):
            same_cwd.append((path, record))
    return same_id + same_project + same_cwd


def _claim(path: Path) -> bool:
    """Atomically take a record file so it resumes (or is announced) at most once."""
    claimed = path.with_name(".%s.claimed-%s" % (path.name, uuid.uuid4().hex[:8]))
    try:
        os.rename(str(path), str(claimed))
    except FileNotFoundError:
        return False
    with contextlib.suppress(OSError):
        claimed.unlink()
    return True


def consume_pending(layout: Layout, session_id: str, cwd: str, now: float, window_minutes: int,
                    project_dir: Optional[str] = None) -> Optional[PendingRecord]:
    """Take the record for a session that has just been cleared.

    Same session id first; then the newest record from the same project folder (the parent
    directory of the session's transcript file, which stays put even if the session's cwd moved
    mid-run via `cd`); then, as a fallback for records with no project_dir, the newest record from
    the same cwd. Records older than the window are left in place (see consume_expired_pending)
    rather than resumed; records past the 24h notice horizon are deleted outright. Consuming is an
    atomic rename, so a record resumes at most one session."""
    try:
        paths = _list_records(layout)
    except FileNotFoundError:
        return None
    window = window_minutes * 60
    valid = [(path, record) for path, record, age in _sweep(paths, now, window) if age <= window]
    for path, record in _match_levels(valid, session_id, cwd, project_dir):
        if _claim(path):
            return record
    return None


def consume_expired_pending(layout: Layout, session_id: str, cwd: str, now: float, window_minutes: int,
                            project_dir: Optional[str] = None) -> Optional[PendingRecord]:
    """The counterpart to consume_pending for the "checkpoint scaduto" notice: finds the newest record
    that matches this session the same way a resume would (same session id, then project folder, then
    cwd) but has expired — past the window, still within the 24h notice horizon — claims it the same
    atomic way, and returns it. A record whose checkpoint file no longer exists is dropped silently
    and the search continues with the next match. Returns None if nothing in the notice horizon
    matches; a still-valid record is consume_pending's job, not this one's."""
    try:
        paths = _list_records(layout)
    except FileNotFoundError:
        return None
    window = window_minutes * 60
    expired = [(path, record) for path, record, age in _sweep(paths, now, window) if age > window]
    for path, record in _match_levels(expired, session_id, cwd, project_dir):
        if not _claim(path):
            continue
        if not os.path.exists(record.checkpoint):
            continue
        return record
    return None
