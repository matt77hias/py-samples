#!/usr/bin/env python3
"""
Normalize comic archives in a Calibre library:

  * every CBR/CBT/CB7 -> converted to CBZ (lossless page passthrough), the new
    CBZ registered with Calibre and the old format removed
  * every CBZ          -> repacked so page filenames follow the zero-padded
    convention (001.jpg, 002.jpg, ...); files already conforming are skipped
  * ComicInfo.xml is preserved across every rewrite

The script makes TWO passes: the first counts the candidate files so a progress
bar can be shown; the second does the work.

Calibre integration uses the `calibredb` CLI. The Calibre GUI must be CLOSED
while this runs against a local library (calibredb requires exclusive access).

    python calibre_normalize.py "D:/Calibre Library"
    python calibre_normalize.py "D:/Calibre Library" --dry-run   # log only
    python calibre_normalize.py "D:/Calibre Library" --no-calibre  # files only

See comic_lib for imaging dependencies (rarfile + unrar needed for CBR;
py7zr needed for CB7).
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import comic_lib as cl
from calibre_lib import ProgressBar, book_id_from_path

_NON_CBZ_EXTS = {".cbr", ".cbt", ".cb7"}
_ALL_ARCHIVE_EXTS = _NON_CBZ_EXTS | {".cbz"}


def calibredb_swap_format(
    calibredb: str,
    library_root: Path,
    book_id: int,
    cbz_path: Path,
    old_fmt: str,
) -> None:
    """Register the CBZ format and remove old_fmt for `book_id` via calibredb.

    `add_format` replaces any existing CBZ; `remove_format` drops the old format
    from both the Calibre DB and disk. Raises ConversionError if either call
    fails (e.g. GUI open, wrong id)."""
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
        base + ["remove_format", str(book_id), old_fmt.upper()],
        capture_output=True, text=True,
    )
    if rem.returncode != 0:
        raise cl.ConversionError(
            f"calibredb remove_format failed: {rem.stderr.strip() or rem.stdout.strip()}"
        )


# ── Passes ───────────────────────────────────────────────────────────────────

def collect_candidates(library_root: Path) -> list[Path]:
    """First pass: all CBR/CBZ/CBT/CB7 files under the library, in natural order."""
    files = [
        p for p in library_root.rglob("*")
        if p.is_file() and p.suffix.lower() in _ALL_ARCHIVE_EXTS
    ]
    files.sort(key=lambda p: cl.natural_key(str(p)))
    return files


def resolve_archive_pairs(
    candidates: list[Path],
) -> tuple[list[Path], list[Path]]:
    """When any non-CBZ archive (CBR/CBT/CB7) shares a stem with a CBZ in the
    same directory, the CBZ already satisfies the target format, so the other
    archive is IGNORED: left on disk untouched (converting it would overwrite
    the sibling CBZ — silent data loss). The CBZ stays in the worklist.

    Returns (candidates_to_process, ignored)."""
    by_key: dict[tuple, dict[str, Path]] = {}
    for p in candidates:
        key = (p.parent, p.stem.lower())
        by_key.setdefault(key, {})[p.suffix.lower()] = p

    ignored: list[Path] = []
    for slot in by_key.values():
        if ".cbz" in slot:
            for ext in _NON_CBZ_EXTS:
                if ext in slot:
                    ignored.append(slot[ext])

    ignored_set = set(ignored)
    keep = [p for p in candidates if p not in ignored_set]
    return keep, ignored


def process(path: Path, library_root: Path, args, bar: ProgressBar) -> str:
    """Second pass: handle one archive according to `args`.

    CBZ already matching the naming convention is skipped; other CBZ is
    repacked in place. CBR/CBT/CB7 is converted to CBZ, the source replaced
    either by deletion (--no-calibre) or by a calibredb format swap.
    Returns a tally key: 'converted', 'cbz', 'skip', 'dry-convert',
    'dry-cbz', or 'error'."""
    ext = path.suffix.lower()

    if ext == ".cbz":
        if cl.is_normalized_cbz(path):
            return "skip"
        if args.dry_run:
            bar.note(f"WOULD normalize CBZ: {path}")
            return "dry-cbz"
        cl.convert(path, path, "cbz", quality=args.quality, strict_cbz=True,
                   log=bar.note)
        bar.note(f"Normalized CBZ: {path.name}")
        return "cbz"

    # Non-CBZ archive: convert to CBZ.
    fmt_upper = ext.lstrip(".").upper()
    cbz_path = path.with_suffix(".cbz")
    book_id = book_id_from_path(path, library_root)

    if args.dry_run:
        target = f"book {book_id}" if book_id is not None else "UNKNOWN book id"
        cal = "" if args.no_calibre else f" + calibredb swap ({target})"
        bar.note(f"WOULD convert {fmt_upper} -> CBZ: {path}{cal}")
        return "dry-convert"

    if cbz_path.exists() and not args.overwrite:
        raise cl.ConversionError(f"target already exists: {cbz_path.name} (use --overwrite)")

    cl.convert(path, cbz_path, "cbz", quality=args.quality, log=bar.note)

    if args.no_calibre:
        path.unlink()
        bar.note(f"Converted (files only): {path.name} -> {cbz_path.name}")
        return "converted"

    if book_id is None:
        bar.note(
            f"WARN: converted {path.name} but could not find Calibre book id "
            f"in path; {fmt_upper} left in place, CBZ written alongside: {cbz_path}"
        )
        return "error"

    calibredb_swap_format(args.calibredb, library_root, book_id, cbz_path, fmt_upper)
    bar.note(f"Converted + Calibre updated (book {book_id}): {path.name} -> {cbz_path.name}")
    return "converted"


# ── CLI ──────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the Calibre normalizer CLI."""
    p = argparse.ArgumentParser(
        description="Normalize CBR/CBT/CB7/CBZ archives in a Calibre library to padded-name CBZ.",
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
                   help="Overwrite an existing .cbz when converting a source archive")
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

    if not args.dry_run and not args.no_calibre:
        if shutil.which(args.calibredb) is None and not Path(args.calibredb).exists():
            sys.exit(
                f"calibredb not found: '{args.calibredb}'. Put it on PATH, pass "
                "--calibredb PATH, or use --no-calibre to only replace files."
            )

    print(f"Scanning library: {library_root}")
    candidates = collect_candidates(library_root)
    if not candidates:
        sys.exit("No CBR/CBZ/CBT/CB7 files found.")
    print(f"Found {len(candidates)} archive(s).")

    candidates, ignored = resolve_archive_pairs(candidates)
    if ignored:
        print(f"\nWARNING: {len(ignored)} archive(s) ignored because a CBZ with "
              "the same name exists (left as-is; the CBZ is handled normally):")
        for p in ignored:
            print(f"  - {p}")
        print()
    if not candidates:
        sys.exit("Nothing to do.")

    if not args.dry_run:
        if not cl.can_read_rar() and any(p.suffix.lower() == ".cbr" for p in candidates):
            sys.exit(
                "CBR files present but no RAR-reading tool found. Install 'unrar' "
                "(or 7-Zip), set COMIC_UNRAR, or pass --unrar PATH. Refusing to "
                "run to avoid dropping pages."
            )
        if cl.py7zr is None and any(p.suffix.lower() == ".cb7" for p in candidates):
            sys.exit(
                "CB7 files present but py7zr is not installed. "
                "Install with: pip install py7zr"
            )

    if args.dry_run:
        print("DRY RUN - no files will be changed.\n")

    bar = ProgressBar(len(candidates), enabled=not args.no_progress and not args.dry_run)
    tally = {"converted": 0, "cbz": 0, "skip": 0, "dry-convert": 0, "dry-cbz": 0, "error": 0}

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
        print(f"  Would convert to CBZ: {tally['dry-convert']}")
        print(f"  CBZ normalize (would repack): {tally['dry-cbz']}")
    else:
        print(f"  Converted to CBZ:     {tally['converted']}")
        print(f"  CBZ normalized:       {tally['cbz']}")
    print(f"  CBZ already OK (skipped):  {tally['skip']}")
    print(f"  Ignored (CBZ sibling exists): {len(ignored)}")
    print(f"  Errors: {tally['error']}")
    sys.exit(1 if tally["error"] else 0)


if __name__ == "__main__":
    main()
