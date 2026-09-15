"""Archive and PDF extraction functions."""

import tarfile
import zipfile
from pathlib import Path
from typing import Iterator, Optional

from ._core import (
    ConversionError, require,
    rarfile, fitz, Image, np, py7zr,
    SUPPORTED_IMAGE_EXTS, METADATA_NAMES,
)
from ._rar import UNRAR_TOOL, RAR_TOOL, can_read_rar
from .page import Page, natural_key


# ── Membership filters ────────────────────────────────────────────────────────

def is_junk(name: str) -> bool:
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


def is_page_entry(name: str) -> bool:
    """True for real image pages."""
    if is_junk(name):
        return False
    return Path(name).suffix.lower() in SUPPORTED_IMAGE_EXTS


def is_preservable_extra(name: str) -> bool:
    """True for a root-level reader-metadata member (ComicInfo.xml)."""
    if is_junk(name):
        return False
    if name != Path(name).name:
        return False
    return Path(name).name.lower() in METADATA_NAMES


# ── Archive extraction ────────────────────────────────────────────────────────

def _extract_archive(names, reader, kind: str, strict: bool = False, log=print) -> list[Page]:
    """Turn archive entries into ordered Pages."""
    image_names = sorted(
        (n for n in names if is_page_entry(n)),
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


def extract_from_cbt(path: Path, log=print) -> list[Page]:
    """Extract ordered Pages from a CBT (TAR) archive."""
    try:
        with tarfile.open(path) as tf:
            members = {m.name: m for m in tf.getmembers() if is_page_entry(m.name)}
            image_names = sorted(members, key=natural_key)
            if not image_names:
                raise ConversionError(f"no image pages found in CBT '{path.name}'")
            pages: list[Page] = []
            for name in image_names:
                try:
                    f = tf.extractfile(members[name])
                    if f is None:
                        raise ConversionError("not a regular file")
                    pages.append(Page(data=f.read(), ext=Path(name).suffix))
                except Exception as e:
                    log(f"  Warning: could not read '{name}': {e}")
                    pages.append(Page(missing=True))
            return pages
    except tarfile.TarError as e:
        raise ConversionError(f"could not open CBT '{path.name}': {e}")


def extract_from_cb7(path: Path, log=print) -> list[Page]:
    """Extract ordered Pages from a CB7 (7-Zip) archive."""
    require(py7zr, "py7zr", "pip install py7zr")
    try:
        with py7zr.SevenZipFile(path, mode="r") as zf:
            image_names = sorted(
                (n for n in zf.getnames() if is_page_entry(n)),
                key=natural_key,
            )
            if not image_names:
                raise ConversionError(f"no image pages found in CB7 '{path.name}'")
            # py7zr has no random-access API: read() decompresses all requested
            # members in one pass. Unlike CBZ/CBR (one page at a time), all page
            # bytes are in memory simultaneously until the loop below consumes them.
            extracted = zf.read(image_names)
            pages: list[Page] = []
            for name in image_names:
                try:
                    bio = extracted.get(name)
                    if bio is None:
                        raise ConversionError("file missing from archive")
                    pages.append(Page(data=bio.read(), ext=Path(name).suffix))
                except Exception as e:
                    log(f"  Warning: could not read '{name}': {e}")
                    pages.append(Page(missing=True))
            return pages
    except py7zr.Bad7zFile as e:
        raise ConversionError(f"could not open CB7 '{path.name}': {e}")


def _native_dpi(page) -> Optional[float]:
    """Highest embedded-image resolution on the page, expressed as a page DPI,
    or None if the page carries no raster image.

    For each placed image, its own density is its pixel size divided by the
    physical size of its placement box (points/72 = inches). Rendering the page
    at that DPI reproduces the image at its native pixel count; going higher only
    upscales (interpolates) it, inflating output size without adding detail. The
    max across images preserves the sharpest content on the page."""
    try:
        infos = page.get_image_info()
    except Exception:
        return None
    best: Optional[float] = None
    for info in infos:
        w = info.get("width", 0)
        h = info.get("height", 0)
        bbox = info.get("bbox")
        if not w or not h or bbox is None:
            continue
        bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if bw <= 0 or bh <= 0:
            continue
        cand = max(w / (bw / 72.0), h / (bh / 72.0))
        if best is None or cand > best:
            best = cand
    return best


def extract_from_pdf(
    path: Path,
    dpi: int,
    pdf_color_mode: str = "color",
    no_upscale: bool = False,
    log=print,
) -> Iterator[Page]:
    """Rasterize each PDF page to an image Page at the given dpi, lazily.

    Yields one Page at a time so callers can encode-and-release each rendered
    bitmap before the next is decoded, keeping peak memory to a single page
    instead of the whole document.

    pdf_color_mode: "color" (RGB), "greyscale" (L-mode), or "auto" (per-page
    detection, requires numpy).

    no_upscale: when True, clamp each page's render DPI to the native resolution
    of its embedded image, so scanned pages are never interpolated above the
    detail the source actually holds (dpi stays the ceiling)."""
    if pdf_color_mode not in ("color", "greyscale", "auto"):
        raise ConversionError(f"unknown pdf_color_mode: '{pdf_color_mode}'")
    require(fitz, "PyMuPDF", "pip install PyMuPDF")
    require(Image, "Pillow", "pip install Pillow")
    if pdf_color_mode == "auto":
        require(np, "numpy", "pip install numpy")
    doc = fitz.open(str(path))
    if doc.page_count == 0:
        doc.close()
        raise ConversionError("PDF has no pages")

    def _render() -> Iterator[Page]:
        try:
            clamped = 0
            total_pages = doc.page_count
            for i, page in enumerate(doc):
                try:
                    page_dpi = dpi
                    if no_upscale:
                        native = _native_dpi(page)
                        if native is not None and native < dpi:
                            page_dpi = native
                            clamped += 1
                    mat = fitz.Matrix(page_dpi / 72, page_dpi / 72)
                    if pdf_color_mode == "greyscale":
                        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
                        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
                    elif pdf_color_mode == "auto":
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
                    yield Page(image=img)
                except Exception as e:
                    log(f"  Warning: could not render PDF page {i + 1}: {e}")
                    yield Page(missing=True)
            if no_upscale and clamped:
                log(f"  --no-upscale: clamped {clamped}/{total_pages} page(s) to native DPI (below {dpi})")
        finally:
            doc.close()

    return _render()


_7Z_MAGIC = b"7z\xbc\xaf\x27\x1c"


def detect_format(path: Path) -> Optional[str]:
    """Identify the real container from its contents: "cbz", "cbr", "pdf", "cbt", "cb7", or None."""
    try:
        if zipfile.is_zipfile(path):
            return "cbz"
        if rarfile is not None and rarfile.is_rarfile(path):
            return "cbr"
        with open(path, "rb") as f:
            header = f.read(6)
        if header[:5] == b"%PDF-":
            return "pdf"
        if header == _7Z_MAGIC:
            return "cb7"
        try:
            if tarfile.is_tarfile(path):
                return "cbt"
        except Exception:
            pass
    except OSError:
        return None
    return None


def extract_images(
    path: Path,
    pdf_dpi: int,
    strict_cbz: bool = False,
    pdf_color_mode: str = "color",
    no_upscale: bool = False,
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
    if fmt == "cbt":
        return extract_from_cbt(path, log=log)
    if fmt == "cb7":
        return extract_from_cb7(path, log=log)
    if fmt == "pdf":
        return extract_from_pdf(path, pdf_dpi, pdf_color_mode=pdf_color_mode,
                                no_upscale=no_upscale, log=log)
    raise ConversionError(f"unsupported or unrecognized source format: '{path.name}'")


def _read_extras(namelist, reader) -> dict[str, bytes]:
    """Collect {name: bytes} for root-level reader-metadata members."""
    extras: dict[str, bytes] = {}
    for name in namelist:
        if is_preservable_extra(name):
            try:
                extras[name] = reader(name)
            except Exception:
                pass
    return extras


def archive_extras(path: Path) -> dict[str, bytes]:
    """Return preservable reader-metadata (ComicInfo.xml) from a CBZ/CBR/CBT/CB7."""
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
        if fmt == "cbt":
            with tarfile.open(path) as tf:
                extras: dict[str, bytes] = {}
                for member in tf.getmembers():
                    if is_preservable_extra(member.name):
                        f = tf.extractfile(member)
                        if f:
                            extras[member.name] = f.read()
                return extras
        if fmt == "cb7" and py7zr is not None:
            with py7zr.SevenZipFile(path, mode="r") as zf:
                meta = [n for n in zf.getnames() if is_preservable_extra(n)]
                if not meta:
                    return {}
                extracted = zf.read(meta)
                return {n: bio.read() for n, bio in extracted.items() if bio}
    except Exception:
        return {}
    return {}
