"""Shared helpers for Calibre CLI scripts (calibre_normalize, calibre_regen_cbz)."""

import re
import sys
from pathlib import Path
from typing import Optional

_BOOK_ID_RE = re.compile(r"\((\d+)\)\s*$")


class ProgressBar:
    """A minimal single-line terminal progress bar (no external deps). Disables
    itself when not wanted or when there is nothing to count."""

    def __init__(self, total: int, width: int = 40, enabled: bool = True):
        self.total = total
        self.width = width
        self.enabled = enabled and total > 0
        self.n = 0

    def update(self, label: str = "") -> None:
        """Advance the bar by one step and redraw it with an optional label."""
        self.n += 1
        if not self.enabled:
            return
        frac = self.n / self.total
        filled = int(self.width * frac)
        bar = "#" * filled + "-" * (self.width - filled)
        label = (label[:30]).ljust(30)
        sys.stdout.write(f"\r[{bar}] {self.n}/{self.total}  {label}")
        sys.stdout.flush()

    def note(self, msg: str) -> None:
        """Print a line above the bar without corrupting it."""
        if self.enabled:
            sys.stdout.write("\r" + " " * (self.width + 60) + "\r")
        print(msg)

    def close(self) -> None:
        """Finish the bar with a trailing newline so later output starts fresh."""
        if self.enabled:
            sys.stdout.write("\n")
            sys.stdout.flush()


def book_id_from_path(path: Path, library_root: Path) -> Optional[int]:
    """Extract the Calibre book id from the containing folder name Title (123).
    Search upward from the file toward the library root to be safe."""
    for parent in path.parents:
        if parent == library_root.parent:
            break
        m = _BOOK_ID_RE.search(parent.name)
        if m:
            return int(m.group(1))
    return None
