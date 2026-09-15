#!/usr/bin/env python3
"""
Normalize comic archives in a Calibre library:

  * every CBR  -> converted to CBZ (lossless page passthrough), the new CBZ
    registered with Calibre and the old CBR format removed
  * every CBZ  -> repacked so page filenames follow the zero-padded convention
    (001.jpg, 002.jpg, ...); files already conforming are skipped
  * ComicInfo.xml is preserved across every rewrite

The script makes TWO passes: the first counts the candidate files so a progress
bar can be shown; the second does the work.

Calibre integration uses the `calibredb` CLI. The Calibre GUI must be CLOSED
while this runs against a local library (calibredb requires exclusive access).

    python calibre_normalize.py "D:/Calibre Library"
    python calibre_normalize.py "D:/Calibre Library" --dry-run   # log only
    python calibre_normalize.py "D:/Calibre Library" --no-calibre  # files only

See comic_lib.py for imaging dependencies (rarfile + unrar are needed to read CBR).
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

import comic_lib as cl

# Calibre names each book folder "Title (<id>)"; grab the trailing id.
_BOOK_ID_RE = re.compile(r"\((\d+)\)\s*$")


# ── Progress bar (no external deps) ──────────────────────────────────────────

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


# ── Calibre helpers ──────────────────────────────────────────────────────────

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


def calibredb_swap_format(
    calibredb: str,
    library_root: Path,
    book_id: int,
    cbz_path: Path,
) -> None:
    """Register the CBZ format and remove the CBR format for `book_id` via the
    calibredb CLI. `add_format` replaces any existing CBZ; `remove_format` drops
    the CBR from both the Calibre DB and disk. Raises ConversionError if either
    calibredb call fails (e.g. GUI open, wrong id)."""
    base = [calibredb, "--library-path", str(library_root)]
    add = subprocess.run(
        base + ["add_format", str(book_id), str(cbz_path)],
        capture_output=True, text=True,
    )
    if add.returncode != 0:
        raise cl.ConversionError(
            f"calibredb add_format failed: {add.stderr.strip() or add.stdout.strip()}"
        )
    rem = subprocess.run(
        base + ["remove_format", str(book_id), "CBR"],
        capture_output=True, text=True,
    )
    if rem.returncode != 0:
        raise cl.ConversionError(
            f"calibredb remove_format failed: {rem.stderr.strip() or rem.stdout.strip()}"
        )


# ── Passes ───────────────────────────────────────────────────────────────────

def collect_candidates(library_root: Path) -> list[Path]:
    """First pass: all CBR/CBZ files under the library, in natural order."""
    files = [
        p for p in library_root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".cbr", ".cbz"}
    ]
    files.sort(key=lambda p: cl.natural_key(str(p)))
    return files


def resolve_cbr_cbz_pairs(
    candidates: list[Path],
) -> tuple[list[Path], list[Path]]:
    """When a CBR and CBZ share a stem in the same directory (e.g. foo.cbr +
    foo.cbz), the CBZ already satisfies the target format, so the CBR is IGNORED:
    left on disk untouched and not converted (converting it would overwrite the
    sibling CBZ - silent data loss). The CBZ stays in the worklist and is
    normalized as usual.

    Returns (candidates_to_process, ignored_cbrs)."""
    by_key = {}  # (dir, stem-lower) -> {ext: path}
    for p in candidates:
        key = (p.parent, p.stem.lower())
        by_key.setdefault(key, {})[p.suffix.lower()] = p

    ignored: list[Path] = []
    for slot in by_key.values():
        if ".cbr" in slot and ".cbz" in slot:
            ignored.append(slot[".cbr"])

    ignored_set = set(ignored)
    keep = [p for p in candidates if p not in ignored_set]
    return keep, ignored


def process(path: Path, library_root: Path, args, bar: ProgressBar) -> str:
    """Second pass: handle one archive according to `args`.

    CBZ already matching the naming convention is skipped; other CBZ is repacked
    in place. CBR is converted to CBZ alongside it, then the source is replaced -
    either by deleting the CBR (`--no-calibre`) or by a calibredb format swap.
    `--dry-run` only logs. Returns a tally key: 'cbr', 'cbz', 'skip', 'dry-cbr',
    'dry-cbz', or 'error'."""
    ext = path.suffix.lower()

    if ext == ".cbz":
        if cl.is_normalized_cbz(path):
            return "skip"
        if args.dry_run:
            bar.note(f"WOULD normalize CBZ: {path}")
            return "dry-cbz"
        # Repack in place: pages are read fully into memory before the atomic
        # write replaces the original, so overwriting the source is safe.
        # strict_cbz=True refuses on any unreadable page rather than silently
        # dropping it and overwriting the source with a shorter file.
        cl.convert(path, path, "cbz", quality=args.quality, strict_cbz=True,
                   log=bar.note)
        bar.note(f"Normalized CBZ: {path.name}")
        return "cbz"

    # ext == ".cbr"
    cbz_path = path.with_suffix(".cbz")
    book_id = book_id_from_path(path, library_root)

    if args.dry_run:
        target = f"book {book_id}" if book_id is not None else "UNKNOWN book id"
        cal = "" if args.no_calibre else f" + calibredb swap ({target})"
        bar.note(f"WOULD convert CBR -> CBZ: {path}{cal}")
        return "dry-cbr"

    if cbz_path.exists() and not args.overwrite:
        raise cl.ConversionError(f"target already exists: {cbz_path.name} (use --overwrite)")

    cl.convert(path, cbz_path, "cbz", quality=args.quality, log=bar.note)

    if args.no_calibre:
        path.unlink()  # replace source: drop the CBR
        bar.note(f"Converted (files only): {path.name} -> {cbz_path.name}")
        return "cbr"

    if book_id is None:
        # Leave both files; can't safely tell Calibre. Report for manual fix.
        bar.note(
            f"WARN: converted {path.name} but could not find Calibre book id "
            f"in path; CBR left in place, CBZ written alongside: {cbz_path}"
        )
        return "error"

    # add_format registers the CBZ; remove_format drops the CBR from DB AND disk.
    calibredb_swap_format(args.calibredb, library_root, book_id, cbz_path)
    bar.note(f"Converted + Calibre updated (book {book_id}): {path.name} -> {cbz_path.name}")
    return "cbr"


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the Calibre normalizer CLI."""
    p = argparse.ArgumentParser(
        description="Normalize CBR/CBZ archives in a Calibre library to padded-name CBZ.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python calibre_normalize.py "D:/Calibre Library"
  python calibre_normalize.py "D:/Calibre Library" --dry-run
  python calibre_normalize.py "D:/Calibre Library" --no-calibre
  python calibre_normalize.py "D:/Calibre Library" --calibredb "C:/Program Files/Calibre2/calibredb.exe"

Close the Calibre GUI before running (calibredb needs exclusive DB access).
""",
    )
    p.add_argument("library", type=Path, help="Path to the Calibre library root")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would happen; convert/replace/update nothing")
    p.add_argument("--no-calibre", action="store_true",
                   help="Replace files on disk but do NOT call calibredb")
    p.add_argument("--calibredb", default="calibredb", metavar="PATH",
                   help="Path to the calibredb executable (default: 'calibredb' on PATH)")
    p.add_argument("--quality", type=int, default=90, metavar="Q",
                   help="JPEG quality for any re-encoded pages, 1-95 (default: 90)")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite an existing .cbz when converting a .cbr")
    p.add_argument("--no-progress", action="store_true", help="Disable the progress bar")
    p.add_argument("--unrar", metavar="PATH",
                   help="Path to the 'unrar' tool for reading CBR (auto-detected)")
    return p


def main() -> None:
    """CLI entry point: parse args, scan the library (first pass), then process
    each archive with a progress bar (second pass) and print a summary. Exits
    non-zero if any file errored."""
    args = build_parser().parse_args()
    args.quality = max(1, min(95, args.quality))
    if args.unrar:
        cl.set_rar_tools(unrar=args.unrar)

    library_root = args.library
    if not library_root.is_dir():
        sys.exit(f"Library not found or not a directory: {library_root}")

    # Verify calibredb up front (unless we won't use it).
    if not args.dry_run and not args.no_calibre:
        if shutil.which(args.calibredb) is None and not Path(args.calibredb).exists():
            sys.exit(
                f"calibredb not found: '{args.calibredb}'. Put it on PATH, pass "
                "--calibredb PATH, or use --no-calibre to only replace files."
            )

    print(f"Scanning library: {library_root}")
    candidates = collect_candidates(library_root)
    if not candidates:
        sys.exit("No CBR/CBZ files found.")
    print(f"Found {len(candidates)} archive(s).")

    # When a CBR and CBZ share a stem, the CBZ already satisfies the target
    # format, so ignore the CBR (converting it would overwrite the sibling CBZ).
    # The CBZ stays in the worklist and is normalized normally.
    candidates, ignored_cbrs = resolve_cbr_cbz_pairs(candidates)
    if ignored_cbrs:
        print(f"\nWARNING: {len(ignored_cbrs)} CBR(s) ignored because a CBZ with "
              "the same name exists (CBR left as-is; the CBZ is handled normally):")
        for cbr in ignored_cbrs:
            print(f"  - {cbr}")
        print()
    if not candidates:
        sys.exit("Nothing to do.")

    # Verify a working RAR reader exists up front if any CBR will be read.
    # Failing here (before any conversion/deletion) prevents silent page loss
    # from a missing/broken unrar tool.
    if not args.dry_run and not cl.can_read_rar():
        if any(p.suffix.lower() == ".cbr" for p in candidates):
            sys.exit(
                "CBR files present but no RAR-reading tool found. Install 'unrar' "
                "(or 7-Zip), set COMIC_UNRAR, or pass --unrar PATH. Refusing to "
                "run to avoid dropping pages."
            )

    if args.dry_run:
        print("DRY RUN - no files will be changed.\n")

    bar = ProgressBar(len(candidates), enabled=not args.no_progress and not args.dry_run)
    tally = {"cbr": 0, "cbz": 0, "skip": 0, "dry-cbr": 0, "dry-cbz": 0, "error": 0}

    for path in candidates:
        try:
            result = process(path, library_root, args, bar)
            tally[result] += 1
        except cl.ConversionError as e:
            tally["error"] += 1
            bar.note(f"ERROR ({path.name}): {e}")
        except Exception as e:  # noqa: BLE001 - keep the batch alive
            tally["error"] += 1
            bar.note(f"UNEXPECTED ERROR ({path.name}): {e}")
        finally:
            bar.update(path.name)

    bar.close()

    print("\nSummary")
    if args.dry_run:
        print(f"  CBR -> CBZ (would convert): {tally['dry-cbr']}")
        print(f"  CBZ normalize (would repack): {tally['dry-cbz']}")
    else:
        print(f"  CBR -> CBZ converted: {tally['cbr']}")
        print(f"  CBZ normalized:       {tally['cbz']}")
    print(f"  CBZ already OK (skipped): {tally['skip']}")
    print(f"  CBR ignored (CBZ exists): {len(ignored_cbrs)}")
    print(f"  Errors: {tally['error']}")
    sys.exit(1 if tally["error"] else 0)


if __name__ == "__main__":
    main()
