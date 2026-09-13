"""pitstop command line: the hook entry point and the management commands used by the skill."""
import sys
from typing import List, Optional, TextIO

from pitstop.claude.hooks import run_hook
from pitstop.core.paths import Layout, pitstop_home


def write_text(stream: TextIO, text: str) -> None:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:
        stream.write(text)


def read_text(stream: TextIO) -> str:
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        return buffer.read().decode("utf-8", "replace")
    return stream.read()


def _hook(args: List[str], stdin: TextIO, stdout: TextIO, layout: Layout) -> int:
    """Hooks never fail: no argparse exit codes, no stderr noise, always exit 0."""
    try:
        raw = read_text(stdin)
    except Exception:
        return 0
    output = run_hook(args[0] if args else "", raw, layout)
    if output:
        write_text(stdout, output)
    return 0


def main(argv: List[str], stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout,
         layout: Optional[Layout] = None) -> int:
    layout = layout or Layout(pitstop_home())
    if argv[:1] == ["hook"]:
        return _hook(argv[1:], stdin, stdout, layout)
    write_text(stdout, "usage: pitstop hook <stop|post-tool-batch|user-prompt-submit>\n")
    return 2
