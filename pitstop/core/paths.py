"""Layout of pitstop's working directory."""
import os
from pathlib import Path

ENV_HOME = "PITSTOP_HOME"


def pitstop_home() -> Path:
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "pitstop"


class Layout:
    """Paths inside the working directory. Nothing is created here."""

    def __init__(self, base: Path) -> None:
        self.base = base
        self.config = base / "config.json"
        self.state_dir = base / "state"
        self.pending_dir = base / "pending"
        self.checkpoints_dir = base / "checkpoints"
        self.log = base / "log.jsonl"
        self.gaps = base / "gaps.jsonl"
        self.config_notice = base / "config-notice.txt"
