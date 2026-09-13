"""Shared test helpers."""
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
