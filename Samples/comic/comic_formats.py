#!/usr/bin/env python3
"""
Scan a directory of CBR/CBZ/CBT/CB7 files and report the image formats they contain.

Usage:
    python comic_formats.py /path/to/comics
    python comic_formats.py /path/to/comics --ext cbz        # only CBZ
    python comic_formats.py /path/to/comics --summary         # totals only
    python comic_formats.py /path/to/comics --filter webp     # only files containing webp
"""

import argparse
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

import comic_lib as cl

_ALL_EXTS = {".cbz", ".cbr", ".cbt", ".cb7"}


def member_exts_cbz(path: Path) -> Counter:
    try:
        with zipfile.ZipFile(path) as zf:
            return Counter(
                Path(n).suffix.lower()
                for n in zf.namelist()
                if cl.is_page_entry(n)
            )
    except Exception as e:
        print(f"  Warning: could not open {path.name}: {e}", file=sys.stderr)
        return Counter()


def member_exts_cbr(path: Path) -> Counter:
    if cl.rarfile is None:
        print(f"  Warning: rarfile not installed, skipping {path.name}", file=sys.stderr)
        return Counter()
    try:
        with cl.rarfile.RarFile(path) as rf:
            return Counter(
                Path(n).suffix.lower()
                for n in rf.namelist()
                if cl.is_page_entry(n)
            )
    except Exception as e:
        print(f"  Warning: could not open {path.name}: {e}", file=sys.stderr)
        return Counter()


def member_exts_cbt(path: Path) -> Counter:
    try:
        with tarfile.open(path) as tf:
            return Counter(
                Path(n).suffix.lower()
                for n in tf.getnames()
                if cl.is_page_entry(n)
            )
    except Exception as e:
        print(f"  Warning: could not open {path.name}: {e}", file=sys.stderr)
        return Counter()


def member_exts_cb7(path: Path) -> Counter:
    if cl.py7zr is None:
        print(f"  Warning: py7zr not installed, skipping {path.name}", file=sys.stderr)
        return Counter()
    try:
        with cl.py7zr.SevenZipFile(path, mode="r") as zf:
            return Counter(
                Path(n).suffix.lower()
                for n in zf.getnames()
                if cl.is_page_entry(n)
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
    if fmt == "cbt":
        return member_exts_cbt(path)
    if fmt == "cb7":
        return member_exts_cb7(path)
    return Counter()


def collect_archives(root: Path, exts: set[str]) -> list[Path]:
    return sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts),
        key=lambda p: cl.natural_key(str(p)),
    )


def main():
    parser = argparse.ArgumentParser(description="Report image formats inside CBR/CBZ/CBT/CB7 files.")
    parser.add_argument("directory", type=Path, help="Directory to scan (recursive)")
    parser.add_argument("--ext", choices=["cbr", "cbz", "cbt", "cb7"],
                        help="Limit to one archive type")
    parser.add_argument("--summary", action="store_true", help="Print totals only, not per-file breakdown")
    parser.add_argument("--filter", metavar="EXT", help="Only show files containing this image extension (e.g. webp)")
    args = parser.parse_args()

    if not args.directory.is_dir():
        sys.exit(f"Not a directory: {args.directory}")

    scan_exts = {f".{args.ext}"} if args.ext else _ALL_EXTS
    archives = collect_archives(args.directory, scan_exts)

    if not archives:
        print("No CBR/CBZ files found.")
        return

    filter_ext = f".{args.filter.lstrip('.').lower()}" if args.filter else None
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
    print(f"Scanned {len(archives)} archive(s) ({', '.join(sorted(scan_exts))}).")
    if filter_ext:
        print(f"Files containing {filter_ext.lstrip('.')}: {matches}")
    print("Overall image format totals:")
    for ext, count in sorted(totals.items(), key=lambda x: -x[1]):
        print(f"  {ext.lstrip(''):>6}: {count}")


if __name__ == "__main__":
    main()
