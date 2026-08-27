#!/usr/bin/env python3
"""
Comic book format converter: CBR/CBZ/PDF -> CBR/CBZ/PDF (all combinations).

Thin CLI over comic_lib. See comic_lib.py for dependencies and behavior notes.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import comic_lib as cl


def infer_format(dest: Path, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    ext = dest.suffix.lower().lstrip(".")
    if ext in ("cbr", "cbz", "pdf"):
        return ext
    sys.exit(
        f"Cannot infer output format from '{dest}'. "
        "Pass --format cbr|cbz|pdf or give dest a known extension."
    )


def collect_jobs(source: Path, dest: Path, out_fmt: str) -> list[tuple[Path, Path]]:
    """Return (src, dst) pairs, preserving subdirectory structure in batch mode."""
    if source.is_dir():
        # If dest is nested inside source, exclude it so the recursive walk never
        # re-discovers its own output (which would re-convert or grow the tree on
        # repeat runs).
        dest_resolved = dest.resolve()
        def _under_dest(f: Path) -> bool:
            return dest_resolved == f.resolve() or dest_resolved in f.resolve().parents

        srcs = sorted(
            (f for f in source.rglob("*")
             if f.suffix.lower() in cl.SUPPORTED_INPUT_EXTS and not _under_dest(f)),
            key=lambda p: cl.natural_key(str(p)),
        )
        if not srcs:
            sys.exit(f"No CBR/CBZ/PDF files found in {source}")
        jobs = []
        seen: dict[Path, Path] = {}
        for s in srcs:
            rel = s.relative_to(source).with_suffix(f".{out_fmt}")
            dst = dest / rel
            # Two sources sharing a stem (e.g. book.cbr + book.cbz -> book.pdf)
            # would collide; fail loudly rather than silently clobber one.
            if dst in seen:
                sys.exit(
                    f"Output collision: '{seen[dst]}' and '{s}' both map to "
                    f"'{dst}'. Convert them separately or to different folders."
                )
            seen[dst] = s
            jobs.append((s, dst))
        return jobs

    if source.suffix.lower() not in cl.SUPPORTED_INPUT_EXTS:
        sys.exit(f"Unsupported source format: '{source.suffix}'")
    # Single file: dest may be an explicit file path or a target directory.
    if dest.suffix.lower() == f".{out_fmt}":
        return [(source, dest)]
    return [(source, dest / source.with_suffix(f".{out_fmt}").name)]


def convert_file(src: Path, dst: Path, out_fmt: str, args) -> None:
    """Convert one file, honoring --overwrite and guarding against writing a
    file onto itself. Delegates the actual work to comic_lib.convert."""
    if src.resolve() == dst.resolve():
        raise cl.ConversionError("source and destination are the same file")
    if dst.exists() and not args.overwrite:
        print(f"  Skipping (exists): {dst}  (use --overwrite)")
        return

    print(f"Converting: {src.name} -> {dst.name}")
    n = cl.convert(
        src, dst, out_fmt,
        quality=args.quality,
        pdf_dpi=args.pdf_dpi,
        drop_first=args.drop_first,
        drop_last=args.drop_last,
        fill_missing=args.fill_missing,
    )
    print(f"  Wrote {n} pages.")


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the converter CLI."""
    p = argparse.ArgumentParser(
        description="Convert CBR/CBZ/PDF comic files to CBR/CBZ/PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python comic_convert.py book.cbr output.pdf
  python comic_convert.py ./comics/ ./out/ --format cbz
  python comic_convert.py book.cbz book.pdf --drop-first 1 --drop-last 1 --fill-missing white
  python comic_convert.py book.pdf book.cbz --quality 95 --pdf-dpi 200
""",
    )
    p.add_argument("source", type=Path, help="Source file or directory")
    p.add_argument("dest", type=Path, help="Destination file or directory")
    p.add_argument("-f", "--format", choices=["cbr", "cbz", "pdf"],
                   help="Output format (inferred from dest extension if omitted)")
    p.add_argument("--drop-first", type=int, default=0, metavar="N", help="Drop the first N pages")
    p.add_argument("--drop-last", type=int, default=0, metavar="N", help="Drop the last N pages")
    p.add_argument("--fill-missing", choices=["white", "black"], metavar="COLOR",
                   help="Replace unreadable pages with a solid white/black page")
    p.add_argument("--pdf-dpi", type=int, default=150, metavar="DPI",
                   help="DPI for rasterizing PDF input pages (default: 150)")
    p.add_argument("--quality", type=int, default=90, metavar="Q",
                   help="JPEG quality for re-encoded pages, 1-95 (default: 90)")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing destination files")
    p.add_argument("--rar", metavar="PATH",
                   help="Path to the 'rar' create tool for CBR output (auto-detected)")
    p.add_argument("--unrar", metavar="PATH",
                   help="Path to the 'unrar' tool for CBR input (auto-detected)")
    return p


def main() -> None:
    """CLI entry point: validate args, expand source into jobs, convert each,
    and print a summary. Exits non-zero if any file failed."""
    args = build_parser().parse_args()

    if args.drop_first < 0 or args.drop_last < 0:
        sys.exit("--drop-first/--drop-last must be >= 0")
    args.quality = max(1, min(95, args.quality))
    if args.pdf_dpi < 1:
        sys.exit("--pdf-dpi must be >= 1")
    if args.rar or args.unrar:
        cl.set_rar_tools(rar=args.rar, unrar=args.unrar)

    if not args.source.exists():
        sys.exit(f"Source not found: {args.source}")

    out_fmt = infer_format(args.dest, args.format)
    jobs = collect_jobs(args.source, args.dest, out_fmt)

    failures = 0
    for i, (src, dst) in enumerate(jobs, 1):
        if len(jobs) > 1:
            print(f"[{i}/{len(jobs)}]", end=" ")
        try:
            convert_file(src, dst, out_fmt, args)
        except cl.ConversionError as e:
            failures += 1
            print(f"  ERROR ({src.name}): {e}")
        except Exception as e:  # noqa: BLE001 - keep batch alive on unexpected errors
            failures += 1
            print(f"  UNEXPECTED ERROR ({src.name}): {e}")

    done = len(jobs) - failures
    print(f"Done. {done}/{len(jobs)} converted" + (f", {failures} failed." if failures else "."))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
