#!/usr/bin/env python3
"""
Regenerate CBZ from PDF for every book in a Calibre library that has both formats.

For each book folder that contains both a PDF and a CBZ the script:
  1. Converts the PDF -> CBZ using comic_lib (honouring all the usual conversion
     options: DPI, WebP/JPEG, quality, --no-upscale, colour-mode, etc.)
  2. Extracts the first page of the new CBZ as a cover image.
  3. Registers the new CBZ with Calibre via calibredb add_format (replacing the
     old one) and updates the cover via calibredb set_metadata.

The Calibre GUI must be CLOSED while this runs (calibredb requires exclusive DB
access on a local library).

    python calibre_regen_cbz.py "D:/Calibre Library"
    python calibre_regen_cbz.py "D:/Calibre Library" --dry-run
    python calibre_regen_cbz.py "D:/Calibre Library" --no-calibre
    python calibre_regen_cbz.py "D:/Calibre Library" --image-format webp --pdf-dpi 300 --no-upscale
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import comic_lib as cl
from calibre_lib import ProgressBar, book_id_from_path


def calibredb_update(
    calibredb: str,
    library_root: Path,
    book_id: int,
    cbz_path: Path,
    cover_path: Path,
) -> None:
    """Register the new CBZ and update the cover for book_id via calibredb."""
    base = [calibredb, "--library-path", str(library_root)]

    add = subprocess.run(
        base + ["add_format", str(book_id), str(cbz_path)],
        capture_output=True, text=True,
    )
    if add.returncode != 0:
        raise cl.ConversionError(
            f"calibredb add_format failed: {add.stderr.strip() or add.stdout.strip()}"
        )

    meta = subprocess.run(
        base + ["set_metadata", "--field", f"cover:{cover_path}", str(book_id)],
        capture_output=True, text=True,
    )
    if meta.returncode != 0:
        raise cl.ConversionError(
            f"calibredb set_metadata (cover) failed: "
            f"{meta.stderr.strip() or meta.stdout.strip()}"
        )


_COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def extract_cover(cbz_path: Path) -> tuple[bytes, str]:
    """Return (bytes, ext) for the first page in the CBZ (sorted naturally).
    ext is normalised: .jpeg -> .jpg."""
    with zipfile.ZipFile(cbz_path) as zf:
        image_names = sorted(
            (n for n in zf.namelist()
             if Path(n).suffix.lower() in _COVER_EXTS
             and not Path(n).name.startswith(".")),
            key=lambda n: cl.natural_key(n),
        )
        if not image_names:
            raise cl.ConversionError(f"no image pages found in {cbz_path.name}")
        name = image_names[0]
        ext = Path(name).suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        return zf.read(name), ext


# ── Candidate discovery ───────────────────────────────────────────────────────

def collect_candidates(library_root: Path) -> list[tuple[Path, Path]]:
    """Return (pdf, cbz) pairs for every book folder that has both formats.

    Calibre stores each format as a flat file directly inside the book folder,
    so we group by folder and look for exactly one PDF and one CBZ per folder.
    Folders with multiple PDFs or CBZs are skipped with a warning."""
    by_folder: dict[Path, dict[str, list[Path]]] = {}
    for p in library_root.rglob("*"):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in {".pdf", ".cbz"}:
            by_folder.setdefault(p.parent, {}).setdefault(ext, []).append(p)

    pairs = []
    for folder, slot in by_folder.items():
        pdfs = slot.get(".pdf", [])
        cbzs = slot.get(".cbz", [])
        if len(pdfs) > 1 or len(cbzs) > 1:
            print(
                f"WARNING: skipping '{folder.name}' — "
                f"multiple PDFs ({len(pdfs)}) or CBZs ({len(cbzs)}) in one folder; "
                "resolve manually."
            )
            continue
        if pdfs and cbzs:
            pairs.append((pdfs[0], cbzs[0]))

    pairs.sort(key=lambda t: cl.natural_key(str(t[0])))
    return pairs


# ── Per-book processing ───────────────────────────────────────────────────────

def process(
    pdf: Path,
    cbz: Path,
    library_root: Path,
    args,
    bar: ProgressBar,
) -> str:
    """Regen the CBZ from the PDF, refresh the cover. Returns tally key."""
    book_id = book_id_from_path(cbz, library_root)

    if args.dry_run:
        target = f"book {book_id}" if book_id is not None else "UNKNOWN book id"
        cal = "" if args.no_calibre else f" + calibredb update ({target})"
        bar.note(f"WOULD regen CBZ from PDF: {pdf.name}{cal}")
        return "dry"

    if not args.no_calibre and book_id is None:
        bar.note(
            f"WARN: skipping {pdf.name} — could not find Calibre book id in path. "
            "Run with --no-calibre to replace the file without updating Calibre."
        )
        return "skipped"

    bar.note(f"Converting: {pdf.name} -> {cbz.name}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_cbz = Path(tmp) / cbz.name
        cl.convert(
            pdf, tmp_cbz, "cbz",
            quality=args.quality,
            pdf_dpi=args.pdf_dpi,
            image_format=args.image_format,
            pdf_color_mode=args.pdf_color_mode,
            no_upscale=args.no_upscale,
            log=bar.note,
        )

        cover_data, cover_ext = extract_cover(tmp_cbz)

        if args.no_calibre:
            shutil.move(str(tmp_cbz), cbz)
            bar.note(f"  Replaced (files only): {cbz.name}")
            return "done"

        # Write cover to a temp file alongside the CBZ temp dir so calibredb can
        # read it; both are cleaned up when the TemporaryDirectory is removed.
        cover_path = Path(tmp) / f"cover{cover_ext}"
        cover_path.write_bytes(cover_data)

        calibredb_update(args.calibredb, library_root, book_id, tmp_cbz, cover_path)
        bar.note(f"  Updated Calibre (book {book_id}): {cbz.name} + cover")

    return "done"


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Regenerate CBZ from PDF for Calibre books that have both formats.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python calibre_regen_cbz.py "D:/Calibre Library"
  python calibre_regen_cbz.py "D:/Calibre Library" --dry-run
  python calibre_regen_cbz.py "D:/Calibre Library" --no-calibre
  python calibre_regen_cbz.py "D:/Calibre Library" --image-format webp --pdf-dpi 300 --no-upscale --quality 92
  python calibre_regen_cbz.py "D:/Calibre Library" --pdf-color-mode greyscale

Close the Calibre GUI before running (calibredb needs exclusive DB access).
""",
    )
    p.add_argument("library", type=Path, help="Path to the Calibre library root")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would happen without converting or updating anything")
    p.add_argument("--no-calibre", action="store_true",
                   help="Replace CBZ files on disk but do NOT call calibredb")
    p.add_argument("--calibredb", default="calibredb", metavar="PATH",
                   help="Path to the calibredb executable (default: 'calibredb' on PATH)")
    p.add_argument("--pdf-dpi", type=int, default=150, metavar="DPI",
                   help="DPI for rasterizing PDF pages (default: 150)")
    p.add_argument("--no-upscale", action="store_true",
                   help="Never render a PDF page above its embedded image's native resolution")
    p.add_argument("--image-format", choices=["jpeg", "png", "webp"], default=None,
                   metavar="FMT",
                   help="Output image codec: jpeg (default), png, or webp")
    p.add_argument("--pdf-color-mode", choices=["color", "greyscale", "auto"],
                   default="color", metavar="MODE",
                   help="Colour handling: color (default), greyscale, or auto")
    p.add_argument("--quality", type=int, default=90, metavar="Q",
                   help="JPEG/WebP quality 1-95 (default: 90)")
    p.add_argument("--no-progress", action="store_true", help="Disable the progress bar")
    return p


def main() -> None:
    args = build_parser().parse_args()
    args.quality = max(1, min(95, args.quality))
    if args.pdf_dpi < 1:
        sys.exit("--pdf-dpi must be >= 1")

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
    pairs = collect_candidates(library_root)
    if not pairs:
        sys.exit("No books found with both PDF and CBZ formats.")
    print(f"Found {len(pairs)} book(s) with PDF + CBZ.")

    if args.dry_run:
        print("DRY RUN - no files will be changed.\n")

    bar = ProgressBar(len(pairs), enabled=not args.no_progress and not args.dry_run)
    tally = {"done": 0, "dry": 0, "skipped": 0, "error": 0}

    for pdf, cbz in pairs:
        try:
            result = process(pdf, cbz, library_root, args, bar)
            tally[result] += 1
        except cl.ConversionError as e:
            tally["error"] += 1
            bar.note(f"ERROR ({pdf.name}): {e}")
        except Exception as e:  # noqa: BLE001
            tally["error"] += 1
            bar.note(f"UNEXPECTED ERROR ({pdf.name}): {e}")
        finally:
            bar.update(pdf.name)

    bar.close()

    print("\nSummary")
    if args.dry_run:
        print(f"  Would regenerate: {tally['dry']}")
    else:
        print(f"  Regenerated: {tally['done']}")
        if tally["skipped"]:
            print(f"  Skipped (no Calibre book id): {tally['skipped']}")
        if tally["error"]:
            print(f"  Errors:      {tally['error']}")
    sys.exit(1 if tally["error"] else 0)


if __name__ == "__main__":
    main()
