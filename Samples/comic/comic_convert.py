#!/usr/bin/env python3
"""
Comic book format converter: CBR/CBZ/PDF -> CBR/CBZ/PDF (all combinations).

Thin CLI over comic_lib. See comic_lib.py for dependencies and behavior notes.
"""

import argparse
import itertools
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

import comic_lib as cl

_print_lock = threading.Lock()


class Result(Enum):
    """Outcome of a single convert_file call, so main() can tally accurately."""
    CONVERTED = "converted"
    SKIPPED = "skipped"
    DRY_CONVERT = "dry_convert"
    DRY_SKIP = "dry_skip"


@dataclass
class ConvertOptions:
    """Typed conversion options forwarded from the CLI to convert_file and cl.convert."""
    quality: int = 90
    pdf_dpi: int = 150
    image_format: Optional[str] = None
    pdf_color_mode: str = "color"
    no_upscale: bool = False
    drop_first: int = 0
    drop_last: int = 0
    fill_missing: Optional[str] = None
    overwrite: bool = False
    dry_run: bool = False


def infer_format(dest: Path, explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    ext = dest.suffix.lower().lstrip(".")
    if ext in ("cbr", "cbz", "pdf", "cbt", "cb7"):
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


def convert_file(src: Path, dst: Path, out_fmt: str, opts: ConvertOptions, log=print) -> Result:
    """Convert one file, honoring opts.overwrite and guarding against writing a
    file onto itself. Delegates the actual work to comic_lib.convert. Returns a
    Result describing what happened so the caller can tally outcomes."""
    if src.resolve() == dst.resolve():
        raise cl.ConversionError("source and destination are the same file")
    if opts.dry_run:
        if dst.exists() and not opts.overwrite:
            log(f"  Would skip (exists): {dst.name}  (use --overwrite)")
            return Result.DRY_SKIP
        log(f"  Would convert: {src.name} -> {dst.name}")
        return Result.DRY_CONVERT
    if dst.exists() and not opts.overwrite:
        log(f"  Skipping (exists): {dst.name}  (use --overwrite)")
        return Result.SKIPPED

    log(f"Converting: {src.name} -> {dst.name}")
    n = cl.convert(
        src, dst, out_fmt,
        quality=opts.quality,
        pdf_dpi=opts.pdf_dpi,
        image_format=opts.image_format,
        pdf_color_mode=opts.pdf_color_mode,
        no_upscale=opts.no_upscale,
        drop_first=opts.drop_first,
        drop_last=opts.drop_last,
        fill_missing=opts.fill_missing,
        log=log,
    )
    log(f"  Wrote {n} {'page' if n == 1 else 'pages'}.")
    return Result.CONVERTED


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
  python comic_convert.py book.pdf book.cbz --image-format webp --pdf-dpi 300 --no-upscale
  python comic_convert.py book.cbt book.cbz
  python comic_convert.py book.cb7 book.cbz
  python comic_convert.py book.pdf book.cbz --image-format png
  python comic_convert.py book.cbz book.cbz --image-format webp --quality 85
  python comic_convert.py ./comics/ ./out/ --format cbz --image-format webp
  python comic_convert.py book.pdf book.cbz --pdf-color-mode greyscale
  python comic_convert.py book.pdf book.cbz --pdf-color-mode auto
  python comic_convert.py ./comics/ ./out/ --format cbz --workers 4
  python comic_convert.py ./comics/ ./out/ --format cbz --workers 1   # disable parallelism
  python comic_convert.py ./comics/ ./out/ --format cbz --dry-run
""",
    )
    p.add_argument("source", type=Path, help="Source file or directory")
    p.add_argument("dest", type=Path, help="Destination file or directory")
    p.add_argument("-f", "--format", choices=["cbr", "cbz", "pdf", "cbt", "cb7"],
                   help="Output format (inferred from dest extension if omitted)")
    p.add_argument("--drop-first", type=int, default=0, metavar="N", help="Drop the first N pages")
    p.add_argument("--drop-last", type=int, default=0, metavar="N", help="Drop the last N pages")
    p.add_argument("--fill-missing", choices=["white", "black"], metavar="COLOR",
                   help="Replace unreadable pages with a solid white/black page")
    p.add_argument("--pdf-dpi", type=int, default=150, metavar="DPI",
                   help="DPI for rasterizing PDF input pages (default: 150)")
    p.add_argument("--image-format", choices=["jpeg", "png", "webp"], default=None,
                   metavar="FMT",
                   help="Force every output page to this codec (jpeg, png, or webp), for ANY "
                        "source. Enables re-encoding archives, e.g. CBZ(PNG) -> CBZ(WebP). "
                        "When omitted, archive pages keep their original bytes (lossless "
                        "passthrough) and PDF pages default to JPEG. "
                        "Note: webp in PDF output is transcoded to jpeg (PDF containers do not support WebP).")
    p.add_argument("--pdf-color-mode", choices=["color", "greyscale", "auto"], default="color",
                   metavar="MODE",
                   help="Colour handling for rasterized PDF pages: "
                        "color (default) – always RGB; "
                        "greyscale – always L-mode; "
                        "auto – detect per page, store greyscale when no colour is present "
                        "(requires numpy). Only applies when the source is a PDF.")
    p.add_argument("--no-upscale", action="store_true",
                   help="When rasterizing a PDF, never render a page above the native "
                        "resolution of its embedded image. --pdf-dpi stays the ceiling, but "
                        "pages whose source is lower-res are rendered at native instead of "
                        "interpolated up, avoiding bloat with no loss of real detail.")
    p.add_argument("--quality", type=int, default=None, metavar="Q",
                   help="JPEG/WebP quality for re-encoded pages, 1-95 (default: 90). "
                        "Ignored for PNG (lossless).")
    p.add_argument("--overwrite", action="store_true", help="Overwrite existing destination files")
    p.add_argument("--dry-run", action="store_true",
                   help="Log what would be converted without writing any files")
    p.add_argument("--workers", type=int, default=None, metavar="N",
                   help="Number of parallel conversion workers for batch directory mode "
                        "(default: CPU count). Pass 1 to disable parallelism.")
    p.add_argument("--rar", metavar="PATH",
                   help="Path to the 'rar' create tool for CBR output (auto-detected)")
    p.add_argument("--unrar", metavar="PATH",
                   help="Path to the 'unrar' tool for CBR input (auto-detected)")
    return p


def _validate_args(args) -> ConvertOptions:
    """Validate and normalise parsed CLI args; exit on any error. Returns a
    ConvertOptions with all conversion settings ready to use."""
    if args.drop_first < 0 or args.drop_last < 0:
        sys.exit("--drop-first/--drop-last must be >= 0")
    if args.quality is not None and args.image_format == "png":
        print("Warning: --quality has no effect when encoding to png (PNG is lossless).")
    quality = max(1, min(95, args.quality or 90))
    if args.pdf_dpi < 1:
        sys.exit("--pdf-dpi must be >= 1")
    if args.workers is not None and args.workers < 1:
        sys.exit("--workers must be >= 1")
    if args.rar or args.unrar:
        cl.set_rar_tools(rar=args.rar, unrar=args.unrar)
    if not args.source.exists():
        sys.exit(f"Source not found: {args.source}")
    return ConvertOptions(
        quality=quality,
        pdf_dpi=args.pdf_dpi,
        image_format=args.image_format,
        pdf_color_mode=args.pdf_color_mode,
        no_upscale=args.no_upscale,
        drop_first=args.drop_first,
        drop_last=args.drop_last,
        fill_missing=args.fill_missing,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )


def main() -> None:
    """CLI entry point: validate args, expand source into jobs, convert each,
    and print a summary. Exits non-zero if any file failed."""
    args = build_parser().parse_args()
    opts = _validate_args(args)

    if opts.dry_run:
        print("DRY RUN — no files will be written.\n")

    out_fmt = infer_format(args.dest, args.format)
    jobs = collect_jobs(args.source, args.dest, out_fmt)

    # None -> ThreadPoolExecutor uses os.cpu_count(); single-file jobs always run inline.
    workers = args.workers  # None = default (CPU count), or explicit N >= 1
    use_parallel = workers != 1 and len(jobs) > 1

    failures = 0
    total = len(jobs)
    counts = {r: 0 for r in Result}

    if use_parallel:
        # Counter advances once per completed job (any outcome) under the print
        # lock, so it is thread-safe and reaches total even when jobs fail.
        done_counter = itertools.count(1)

        def _run_job_parallel(src: Path, dst: Path) -> Optional[Result]:
            """Run one job; return its Result, or None if it failed (error already
            logged). Output is buffered and flushed atomically under the lock."""
            lines: list[str] = []
            err: Optional[str] = None
            result: Optional[Result] = None
            try:
                result = convert_file(src, dst, out_fmt, opts, log=lines.append)
            except cl.ConversionError as e:
                err = f"  ERROR ({src.name}): {e}"
            except Exception as e:  # noqa: BLE001 - keep batch alive
                err = f"  UNEXPECTED ERROR ({src.name}): {e}"
            with _print_lock:
                n = next(done_counter)
                for line in lines:
                    print(line)
                if err:
                    print(err)
                elif result == Result.CONVERTED:
                    print(f"  [{n}/{total}] Done: {dst.name}")
            return result  # None signals failure to the collector

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_run_job_parallel, src, dst) for src, dst in jobs]
            for future in as_completed(futures):
                result = future.result()
                if result is None:
                    failures += 1
                else:
                    counts[result] += 1
    else:
        for i, (src, dst) in enumerate(jobs, 1):
            if total > 1:
                print(f"[{i}/{total}]", end=" ")
            try:
                counts[convert_file(src, dst, out_fmt, opts)] += 1
            except cl.ConversionError as e:
                failures += 1
                print(f"  ERROR ({src.name}): {e}")
            except Exception as e:  # noqa: BLE001 - keep batch alive
                failures += 1
                print(f"  UNEXPECTED ERROR ({src.name}): {e}")

    if opts.dry_run:
        would_convert = counts[Result.DRY_CONVERT]
        would_skip = counts[Result.DRY_SKIP]
        print(f"Dry run complete. {would_convert}/{len(jobs)} would be converted"
              + (f", {would_skip} would be skipped." if would_skip else "."))
    else:
        parts = [f"{counts[Result.CONVERTED]}/{len(jobs)} converted"]
        if counts[Result.SKIPPED]:
            parts.append(f"{counts[Result.SKIPPED]} skipped")
        if failures:
            parts.append(f"{failures} failed")
        print("Done. " + ", ".join(parts) + ".")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
