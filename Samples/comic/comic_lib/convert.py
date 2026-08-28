"""High-level conversion and normalisation."""

import zipfile
from pathlib import Path
from typing import Optional

from ._core import ConversionError
from .page import Page, natural_key, page_name
from .extract import detect_format, extract_images, archive_extras, _is_page_entry, _is_preservable_extra
from .transform import apply_transforms
from .write import write_output


def convert(
    src: Path,
    dst: Path,
    out_fmt: str,
    *,
    quality: int = 90,
    pdf_dpi: int = 150,
    pdf_image_format: str = "jpeg",
    pdf_color_mode: str = "color",
    drop_first: int = 0,
    drop_last: int = 0,
    fill_missing: Optional[str] = None,
    preserve_metadata: bool = True,
    strict_cbz: bool = False,
    log=print,
) -> int:
    """Convert src to dst in out_fmt. Returns the number of pages written."""
    src_fmt = detect_format(src) or src.suffix.lower().lstrip(".")
    pages = extract_images(src, pdf_dpi, strict_cbz=strict_cbz, pdf_color_mode=pdf_color_mode, log=log)
    pages = apply_transforms(pages, drop_first, drop_last, fill_missing, log=log)
    extras = None
    if preserve_metadata and out_fmt in {"cbz", "cbr"} and src_fmt in {"cbz", "cbr"}:
        extras = archive_extras(src)
    img_fmt = pdf_image_format if src_fmt == "pdf" else "jpeg"
    write_output(pages, dst, out_fmt, quality, extras, img_fmt, log=log)
    return len(pages)


def is_normalized_cbz(path: Path) -> bool:
    """True if path already satisfies the page-naming convention and needs no rewrite."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except Exception:
        return False

    pages: list[str] = []
    for n in names:
        if _is_page_entry(n):
            if n != Path(n).name:
                return False
            pages.append(n)
        elif _is_preservable_extra(n):
            continue
        else:
            return False

    if not pages:
        return False
    ordered = sorted(pages, key=natural_key)
    total = len(ordered)
    for i, n in enumerate(ordered):
        ext = Path(n).suffix.lower()
        if n != page_name(i, total, ext):
            return False
    return True
