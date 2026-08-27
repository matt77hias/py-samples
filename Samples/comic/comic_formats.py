#!/usr/bin/env python3
"""
Scan a directory of CBR/CBZ files and report the image formats they contain.

Usage:
    python comic_formats.py /path/to/comics
    python comic_formats.py /path/to/comics --ext cbz        # only CBZ
    python comic_formats.py /path/to/comics --summary         # totals only
    python comic_formats.py /path/to/comics --filter webp     # only files containing webp
"""

import argparse
import sys
import zipfile
from collections import Counter
from pathlib import Path

try:
    import rarfile
except ImportError:
    rarfile = None

import comic_lib as cl


def member_exts_cbz(path: Path) -> Counter:
    try:
        with zipfile.ZipFile(path) as zf:
            return Counter(
                Path(n).suffix.lower()
                for n in zf.namelist()
                if cl._is_page_entry(n)
            )
    except Exception as e:
        print(f"  Warning: could not open {path.name}: {e}", file=sys.stderr)
        return Counter()


def member_exts_cbr(path: Path) -> Counter:
    if rarfile is None:
        print(f"  Warning: rarfile not installed, skipping {path.name}", file=sys.stderr)
        return Counter()
    try:
        with rarfile.RarFile(path) as rf:
            return Counter(
                Path(n).suffix.lower()
                for n in rf.namelist()
                if cl._is_page_entry(n)
            )
    except Exception as e:
        print(f"  Warning: could not open {path.name}: {e}", file=sys.stderr)
        return Counter()


def member_exts(path: Path) -> Counter:
    fmt = cl.detect_format(path) or path.suffix.lower().lstrip(".")
    if fmt == "cbz":
        return member_exts_cbz(path)
    if fmt == "cbr":
        return member_exts_cbr(path)
    return Counter()


def collect_archives(root: Path, exts: set[str]) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in exts
    )


def main():
    parser = argparse.ArgumentParser(description="Report image formats inside CBR/CBZ files.")
    parser.add_argument("directory", type=Path, help="Directory to scan (recursive)")
    parser.add_argument("--ext", choices=["cbr", "cbz"], help="Limit to one archive type")
    parser.add_argument("--summary", action="store_true", help="Print totals only, not per-file breakdown")
    parser.add_argument("--filter", metavar="EXT", help="Only show files containing this image extension (e.g. webp)")
    args = parser.parse_args()

    if not args.directory.is_dir():
        sys.exit(f"Not a directory: {args.directory}")

    scan_exts = {f".{args.ext}"} if args.ext else {".cbz", ".cbr"}
    archives = collect_archives(args.directory, scan_exts)

    if not archives:
        print("No CBR/CBZ files found.")
        return

    filter_ext = f".{args.filter.lstrip('.')}" if args.filter else None
    totals: Counter = Counter()
    matches = 0

    for path in archives:
        exts = member_exts(path)
        if not exts:
            continue
        totals.update(exts)
        if filter_ext and filter_ext not in exts:
            continue
        matches += 1
        if not args.summary:
            rel = path.relative_to(args.directory)
            ext_summary = ", ".join(
                f"{e.lstrip('.')}: {c}" for e, c in sorted(exts.items())
            )
            print(f"{rel}: {ext_summary}")

    print()
    print(f"Scanned {len(archives)} archive(s).")
    if filter_ext:
        print(f"Files containing {filter_ext.lstrip('.')}: {matches}")
    print("Overall image format totals:")
    for ext, count in sorted(totals.items(), key=lambda x: -x[1]):
        print(f"  {ext.lstrip(''):>6}: {count}")


if __name__ == "__main__":
    main()
