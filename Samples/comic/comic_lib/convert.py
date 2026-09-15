"""High-level conversion and normalisation."""

import contextlib
import zipfile
from pathlib import Path
from typing import Optional

from ._core import ConversionError
from .page import Page, natural_key, page_name
from .extract import detect_format, extract_images, archive_extras, is_page_entry, is_preservable_extra
from .transform import apply_transforms
from .write import write_output

_FMT_EXT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}
# Formats that already discarded detail; re-encoding them to a different codec
# compounds the loss, so we warn before doing it.
_LOSSY_EXTS = {".jpg", ".jpeg", ".webp"}


def convert(
    src: Path,
    dst: Path,
    out_fmt: str,
    *,
    quality: int = 90,
    pdf_dpi: int = 150,
    image_format: Optional[str] = None,
    pdf_color_mode: str = "color",
    no_upscale: bool = False,
    drop_first: int = 0,
    drop_last: int = 0,
    fill_missing: Optional[str] = None,
    preserve_metadata: bool = True,
    strict_cbz: bool = False,
    log=print,
) -> int:
    """Convert src to dst in out_fmt. Returns the number of pages written.

    image_format ("jpeg"/"png"/"webp") forces every output page to that codec,
    for any source — this is what enables e.g. CBZ(PNG) -> CBZ(WebP). When it is
    None, archive pages keep their original bytes (lossless passthrough) and PDF
    pages rasterize to JPEG."""
    src_fmt = detect_format(src) or src.suffix.lower().lstrip(".")

    # Resolve the output codec. A forced image_format wins for every source;
    # otherwise PDF rasterizes to JPEG and archives pass through.
    if image_format is not None:
        forced_fmt: Optional[str] = image_format
    elif src_fmt == "pdf":
        forced_fmt = "jpeg"
    else:
        forced_fmt = None
    # PDF containers cannot embed WebP; fall back to JPEG for PDF output.
    if out_fmt == "pdf" and forced_fmt not in (None, "jpeg", "png"):
        log("  Note: PDF output does not support WebP; encoding pages as JPEG.")
        forced_fmt = "jpeg"

    extracted = extract_images(src, pdf_dpi, strict_cbz=strict_cbz, pdf_color_mode=pdf_color_mode,
                               no_upscale=no_upscale, log=log)

    # PDF extraction is a lazy generator holding an open fitz document. Wrap it
    # in closing() so the document is freed immediately if an exception interrupts
    # _encode_streaming before the generator is exhausted. Lists (archive sources)
    # have no close(), so use nullcontext for them.
    ctx = (contextlib.closing(extracted) if src_fmt == "pdf"
           else contextlib.nullcontext(extracted))
    with ctx as pages_iter:
        if forced_fmt is not None:
            target_ext = _FMT_EXT[forced_fmt]
            # Archives yield a materialized list (safe to inspect source exts); PDF
            # yields a lazy iterator of rasterized pages with no source codec.
            if src_fmt != "pdf":
                _warn_lossy_transcode(pages_iter, target_ext, log)
            # Encode each page to the target codec and release its bitmap right away,
            # keeping peak memory at a single page instead of the whole document.
            pages = list(_encode_streaming(pages_iter, quality, forced_fmt, target_ext))
            img_fmt = forced_fmt
        else:
            pages = pages_iter
            img_fmt = "jpeg"

    pages = apply_transforms(pages, drop_first, drop_last, fill_missing, log=log)
    extras = None
    if preserve_metadata and out_fmt in {"cbz", "cbr", "cbt", "cb7"} and src_fmt in {"cbz", "cbr", "cbt", "cb7"}:
        extras = archive_extras(src)
    write_output(pages, dst, out_fmt, quality, extras, img_fmt, log=log)
    return len(pages)


def _warn_lossy_transcode(pages, target_ext: str, log) -> None:
    """Warn once when lossy source pages are being re-encoded to a different
    codec, since that compounds compression artifacts."""
    changed = sorted({
        p.ext for p in pages
        if not p.missing and p.ext in _LOSSY_EXTS and p.ext != target_ext
    })
    if changed:
        log(f"  Warning: re-encoding lossy pages ({', '.join(changed)}) to "
            f"{target_ext} compounds compression artifacts.")


def _encode_streaming(pages, quality: int, image_format: str, target_ext: str):
    """Encode each page to `image_format`, releasing the decoded bitmap right
    after, and yield a lightweight bytes-backed Page. Pages already in the
    target codec keep their bytes (lossless passthrough)."""
    passthrough = frozenset({target_ext})
    for p in pages:
        if p.missing:
            yield p
            continue
        data, ext = p.encoded(quality, passthrough, image_format)
        p.release()
        yield Page(data=data, ext=ext)


def is_normalized_cbz(path: Path) -> bool:
    """True if path already satisfies the page-naming convention and needs no rewrite."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except Exception:
        return False

    pages: list[str] = []
    for n in names:
        if is_page_entry(n):
            if n != Path(n).name:
                return False
            pages.append(n)
        elif is_preservable_extra(n):
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
