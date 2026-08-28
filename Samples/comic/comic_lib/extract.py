"""Archive and PDF extraction functions."""

import zipfile
from pathlib import Path
from typing import Optional

from ._core import (
    ConversionError, require,
    rarfile, fitz, Image, np,
    SUPPORTED_IMAGE_EXTS, METADATA_NAMES,
)
from ._rar import UNRAR_TOOL, RAR_TOOL, can_read_rar
from .page import Page, natural_key


# ── Membership filters ────────────────────────────────────────────────────────

def _is_junk(name: str) -> bool:
    """True for archive members that should be discarded on a rewrite."""
    if name.endswith("/"):
        return True
    if any(p == "__MACOSX" for p in Path(name).parts):
        return True
    base = Path(name).name
    if base.startswith("._") or base.startswith("."):
        return True
    if base.lower() == "thumbs.db":
        return True
    return False


def _is_page_entry(name: str) -> bool:
    """True for real image pages."""
    if _is_junk(name):
        return False
    return Path(name).suffix.lower() in SUPPORTED_IMAGE_EXTS


def _is_preservable_extra(name: str) -> bool:
    """True for a root-level reader-metadata member (ComicInfo.xml)."""
    if _is_junk(name):
        return False
    if name != Path(name).name:
        return False
    return Path(name).name.lower() in METADATA_NAMES


# ── Archive extraction ────────────────────────────────────────────────────────

def _extract_archive(names, reader, kind: str, strict: bool = False, log=print) -> list[Page]:
    """Turn archive entries into ordered Pages."""
    image_names = sorted(
        (n for n in names if _is_page_entry(n)),
        key=natural_key,
    )
    if not image_names:
        raise ConversionError(f"no image pages found in {kind}")
    pages: list[Page] = []
    for name in image_names:
        try:
            data = reader(name)
            pages.append(Page(data=data, ext=Path(name).suffix))
        except Exception as e:
            if strict:
                raise ConversionError(
                    f"failed to read page '{name}' from {kind}: {e}. "
                    "Refusing to continue (output would be missing pages). "
                    "Check that a working unrar/7z tool is available."
                )
            log(f"  Warning: could not read '{name}': {e}")
            pages.append(Page(missing=True))
    return pages


def extract_from_cbz(path: Path, strict: bool = False, log=print) -> list[Page]:
    """Extract ordered Pages from a CBZ (ZIP) archive."""
    try:
        with zipfile.ZipFile(path) as zf:
            return _extract_archive(zf.namelist(), zf.read, "CBZ", strict=strict, log=log)
    except zipfile.BadZipFile as e:
        raise ConversionError(f"could not open CBZ '{path.name}': {e}")


def extract_from_cbr(path: Path, log=print) -> list[Page]:
    """Extract ordered Pages from a CBR (RAR) archive."""
    require(rarfile, "rarfile", "pip install rarfile  (and put unrar on PATH)")
    if not can_read_rar():
        raise ConversionError(
            "no RAR-reading tool found for CBR. Install 'unrar' (or 7-Zip), or "
            "set COMIC_UNRAR / pass --unrar to point at UnRAR.exe."
        )
    try:
        with rarfile.RarFile(path) as rf:
            return _extract_archive(rf.namelist(), rf.read, "CBR", strict=True, log=log)
    except rarfile.RarCannotExec as e:
        raise ConversionError(
            f"cannot run a RAR-reading tool (tried unrar='{UNRAR_TOOL}'): {e}. "
            "Set COMIC_UNRAR or pass --unrar to a working UnRAR executable."
        )
    except rarfile.Error as e:
        raise ConversionError(f"could not open CBR '{path.name}': {e}")


def extract_from_pdf(
    path: Path,
    dpi: int,
    pdf_color_mode: str = "color",
    log=print,
) -> list[Page]:
    """Rasterize each PDF page to an image Page at the given dpi.

    pdf_color_mode: "color" (RGB), "greyscale" (L-mode), or "auto" (per-page
    detection, requires numpy)."""
    if pdf_color_mode not in ("color", "greyscale", "auto"):
        raise ConversionError(f"unknown pdf_color_mode: '{pdf_color_mode}'")
    require(fitz, "PyMuPDF", "pip install PyMuPDF")
    require(Image, "Pillow", "pip install Pillow")
    pages: list[Page] = []
    with fitz.open(str(path)) as doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for i, page in enumerate(doc):
            try:
                if pdf_color_mode == "greyscale":
                    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
                elif pdf_color_mode == "auto":
                    require(np, "numpy", "pip install numpy")
                    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                    img_rgb = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    arr = np.asarray(img_rgb)
                    is_grey = bool(
                        (arr[:, :, 0] == arr[:, :, 1]).all() and
                        (arr[:, :, 1] == arr[:, :, 2]).all()
                    )
                    img = img_rgb.convert("L") if is_grey else img_rgb
                else:  # "color"
                    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                pages.append(Page(image=img))
            except Exception as e:
                log(f"  Warning: could not render PDF page {i + 1}: {e}")
                pages.append(Page(missing=True))
    if not pages:
        raise ConversionError("PDF has no pages")
    return pages


def detect_format(path: Path) -> Optional[str]:
    """Identify the real container from its contents: "cbz", "cbr", "pdf", or None."""
    try:
        if zipfile.is_zipfile(path):
            return "cbz"
        if rarfile is not None and rarfile.is_rarfile(path):
            return "cbr"
        with open(path, "rb") as f:
            if f.read(5) == b"%PDF-":
                return "pdf"
    except OSError:
        return None
    return None


def extract_images(
    path: Path,
    pdf_dpi: int,
    strict_cbz: bool = False,
    pdf_color_mode: str = "color",
    log=print,
) -> list[Page]:
    """Dispatch to the right extractor by detecting the file's real container."""
    fmt = detect_format(path)
    if fmt is None:
        fmt = path.suffix.lower().lstrip(".")
    if fmt == "cbz":
        return extract_from_cbz(path, strict=strict_cbz, log=log)
    if fmt == "cbr":
        return extract_from_cbr(path, log=log)
    if fmt == "pdf":
        return extract_from_pdf(path, pdf_dpi, pdf_color_mode=pdf_color_mode, log=log)
    raise ConversionError(f"unsupported or unrecognized source format: '{path.name}'")


def _read_extras(namelist, reader) -> dict[str, bytes]:
    """Collect {name: bytes} for root-level reader-metadata members."""
    extras: dict[str, bytes] = {}
    for name in namelist:
        if _is_preservable_extra(name):
            try:
                extras[name] = reader(name)
            except Exception:
                pass
    return extras


def archive_extras(path: Path) -> dict[str, bytes]:
    """Return preservable reader-metadata (ComicInfo.xml) from a CBZ/CBR."""
    fmt = detect_format(path) or path.suffix.lower().lstrip(".")
    try:
        if fmt == "cbz":
            with zipfile.ZipFile(path) as zf:
                return _read_extras(zf.namelist(), zf.read)
        if fmt == "cbr":
            if rarfile is None:
                return {}
            with rarfile.RarFile(path) as rf:
                return _read_extras(rf.namelist(), rf.read)
    except Exception:
        return {}
    return {}
