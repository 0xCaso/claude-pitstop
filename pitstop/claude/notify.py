"""macOS notifications through osascript. Best effort; never blocks or breaks a hook."""
import subprocess
import sys
from typing import Callable, List

_SCRIPT = ["-e", "on run argv", "-e", "display notification (item 1 of argv) with title (item 2 of argv)",
           "-e", "end run"]


def notification_command(title: str, message: str) -> List[str]:
    # Text goes in as arguments, never into the AppleScript source.
    return ["/usr/bin/osascript"] + _SCRIPT + [message, title]


def notify(title: str, message: str, spawn: Callable[..., object] = subprocess.Popen) -> None:
    if sys.platform != "darwin":
        return
    try:
        spawn(notification_command(title, message), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass
