"""Filesystem helpers: private directories, atomic writes, appends and advisory locks."""
import contextlib
import errno
import fcntl
import os
import tempfile
import time
from pathlib import Path
from typing import Iterator

DIR_MODE = 0o700
FILE_MODE = 0o600


class LockTimeout(Exception):
    """Another process holds the lock for longer than the timeout."""


def ensure_dir(path: Path) -> Path:
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    return path


def atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, then rename over the target."""
    ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def append_line(path: Path, line: str) -> None:
    """Append one line with a single write, so concurrent appenders do not interleave."""
    ensure_dir(path.parent)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
    finally:
        os.close(fd)


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 2.0) -> Iterator[None]:
    """Exclusive flock. The kernel releases it when the holder dies, so a lock file
    left behind by a crashed process never blocks anyone."""
    ensure_dir(path.parent)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, FILE_MODE)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if time.monotonic() >= deadline:
                    raise LockTimeout(str(path)) from None
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
