#!/usr/bin/env python3
"""
Shared library for comic-book archive handling (CBR/CBZ/PDF).

Used by:
    comic_convert.py     - general format converter CLI
    calibre_normalize.py - Calibre-library CBZ normalizer

Dependencies (all optional; each is only required for the paths that use it):
    pip install rarfile Pillow PyMuPDF img2pdf
    # CBR input  needs the 'unrar' CLI on PATH
    # CBR output needs the 'rar'   CLI on PATH (https://www.rarlab.com/)

Lossless where possible: archive->archive and archive->PDF keep the original
JPEG/PNG bytes untouched. Re-encoding only happens for PDF input, blank filler
pages, or non-JPEG/PNG source images.
"""

import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

# ── Optional dependency imports ──────────────────────────────────────────────

try:
    import rarfile
except ImportError:
    rarfile = None  # type: ignore[assignment]

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[assignment]

try:
    import img2pdf
except ImportError:
    img2pdf = None  # type: ignore[assignment]

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
SUPPORTED_INPUT_EXTS = {".cbr", ".cbz", ".pdf"}
# Extensions that CBZ/CBR readers and img2pdf accept without transcoding.
PASSTHROUGH_EXTS = {".jpg", ".jpeg", ".png"}
# WebP is supported by most modern CBZ/CBR readers and can be stored in ZIP/RAR
# without decoding; PDF output still transcodes (img2pdf/fitz don't support WebP).
ARCHIVE_PASSTHROUGH_EXTS = PASSTHROUGH_EXTS | {".webp"}
# Root-level non-image members preserved across a rewrite (reader metadata only;
# arbitrary sidecars like credits.txt are intentionally dropped).
METADATA_NAMES = {"comicinfo.xml"}


# ── RAR tool resolution ──────────────────────────────────────────────────────
# WinRAR ships 'Rar.exe'/'UnRAR.exe' and does NOT add itself to PATH, so we probe
# common install locations and env vars. RAR (create) and UNRAR (extract) are
# separate tools: unrar cannot create archives. Overridable via set_rar_tools().

def _probe_tool(names: tuple[str, ...], env_var: str) -> Optional[str]:
    """Find an executable by env var override, then PATH, then known install
    dirs. Returns an absolute path or a bare command name, else None."""
    override = os.environ.get(env_var)
    if override:
        return override  # trust the user; existence checked at call time
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    search_dirs = [
        r"C:\Program Files\WinRAR",
        r"C:\Program Files (x86)\WinRAR",
        "/usr/bin", "/usr/local/bin", "/opt/homebrew/bin",
    ]
    for d in search_dirs:
        for name in names:
            cand = Path(d) / name
            if cand.exists():
                return str(cand)
    return None


# Extract tool: a genuine unrar-compatible CLI (unrar / WinRAR's UnRAR.exe).
# Only this goes into rarfile.UNRAR_TOOL; rarfile has its own separate slots and
# auto-fallback for bsdtar/7z/unar, so we must NOT put those here (different args).
UNRAR_TOOL: Optional[str] = _probe_tool(("unrar", "UnRAR.exe", "unrar.exe"), "COMIC_UNRAR")
# Create tool: only rar/Rar.exe can write RAR archives.
RAR_TOOL: Optional[str] = _probe_tool(("rar", "Rar.exe", "rar.exe"), "COMIC_RAR")

if rarfile is not None and UNRAR_TOOL:
    rarfile.UNRAR_TOOL = UNRAR_TOOL


def can_read_rar() -> bool:
    """True if some RAR-reading backend is available: our detected unrar, or a
    tool rarfile can use on its own (unar/bsdtar/7z on PATH)."""
    if rarfile is None:
        return False
    if UNRAR_TOOL:
        return True
    for tool in (getattr(rarfile, "UNAR_TOOL", "unar"),
                 getattr(rarfile, "BSDTAR_TOOL", "bsdtar"),
                 getattr(rarfile, "SEVENZIP_TOOL", "7z"),
                 getattr(rarfile, "SEVENZIP2_TOOL", "7zz")):
        if shutil.which(tool):
            return True
    return False


def set_rar_tools(rar: Optional[str] = None, unrar: Optional[str] = None) -> None:
    """Override the detected rar (create) and/or unrar (extract) tool paths.
    Called by the CLIs when --rar/--unrar are supplied."""
    global RAR_TOOL, UNRAR_TOOL
    if rar:
        RAR_TOOL = rar
    if unrar:
        UNRAR_TOOL = unrar
        if rarfile is not None:
            rarfile.UNRAR_TOOL = unrar


class ConversionError(Exception):
    """Raised for a single-file failure so batch callers can continue."""


# ── Page model ───────────────────────────────────────────────────────────────

class Page:
    """A single comic page, carrying original encoded bytes when available so
    conversions can avoid re-encoding."""

    __slots__ = ("data", "ext", "_image", "missing")

    def __init__(self, data=None, ext=None, image=None, missing=False):
        """Create a page from encoded bytes (`data` + `ext`), a decoded PIL
        `image`, or neither with `missing=True` to mark an unreadable slot."""
        self.data: Optional[bytes] = data
        self.ext: Optional[str] = ext.lower() if ext else None
        self._image: Optional["PILImage"] = image
        self.missing: bool = missing

    def pil(self) -> "PILImage":
        """Decode to an RGB PIL image (cached)."""
        if self._image is None:
            if self.data is None:
                raise ConversionError("page has no data to decode")
            require(Image, "Pillow", "pip install Pillow")
            img = Image.open(io.BytesIO(self.data))
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.load()
            self._image = img
        elif self._image.mode != "RGB":
            self._image = self._image.convert("RGB")
        return self._image

    def size(self) -> tuple[int, int]:
        """Return (width, height) in pixels; decodes the page if needed."""
        return self.pil().size

    def encoded(self, quality: int, passthrough_exts: frozenset[str] = frozenset(PASSTHROUGH_EXTS)) -> tuple[bytes, str]:
        """Return (bytes, extension) ready to store. Passes original bytes
        through untouched for extensions in passthrough_exts; otherwise encodes to JPEG."""
        if self.data is not None and self.ext in passthrough_exts:
            return self.data, self.ext
        buf = io.BytesIO()
        self.pil().save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue(), ".jpg"


# ── Helpers ──────────────────────────────────────────────────────────────────

def natural_key(s: str):
    """Sort key so page2 < page10 (lexicographic sort gets this wrong)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def page_name(index: int, total: int, ext: str = ".jpg") -> str:
    """Zero-padded page filename. Width scales with total page count:
    <10 -> 1,2,3 ; <100 -> 01,02,03 ; <1000 -> 001,002,003 ; etc."""
    digits = max(1, len(str(total)))
    return f"{index + 1:0{digits}d}{ext}"


def blank_page(width: int, height: int, color: str) -> Page:
    """Build a solid white or black filler page at the given resolution."""
    rgb = (255, 255, 255) if color == "white" else (0, 0, 0)
    return Page(image=Image.new("RGB", (width, height), rgb))


def require(module, name: str, hint: str) -> None:
    """Raise ConversionError if an optional dependency `module` is None (not
    installed), pointing the user at the install `hint`."""
    if module is None:
        raise ConversionError(f"Missing dependency '{name}'. Install with: {hint}")


# ── Extraction ───────────────────────────────────────────────────────────────

def _is_junk(name: str) -> bool:
    """True for archive members that should be discarded on a rewrite: directory
    entries, macOS __MACOSX/._* resource forks, dotfiles, and Thumbs.db."""
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
    """True for real image pages; skips directories and junk metadata files
    (macOS __MACOSX/._* resource forks, dotfiles like .DS_Store, Thumbs.db)."""
    if _is_junk(name):
        return False
    return Path(name).suffix.lower() in SUPPORTED_IMAGE_EXTS


def _is_preservable_extra(name: str) -> bool:
    """True for a root-level reader-metadata member worth carrying across a
    rewrite (currently ComicInfo.xml; see METADATA_NAMES). Nested copies and
    arbitrary sidecars (credits.txt, *.nfo, ...) are intentionally excluded."""
    if _is_junk(name):
        return False
    if name != Path(name).name:  # not at root
        return False
    return Path(name).name.lower() in METADATA_NAMES


def _extract_archive(names, reader, kind: str, strict: bool = False) -> list[Page]:
    """Turn an archive's entries into ordered Pages. `names` is the member list,
    `reader(name)->bytes` fetches one member, `kind` labels errors. Real image
    pages are kept in natural order (raw bytes, no decode). Raises if no image
    pages are found.

    A page that fails to read becomes a missing-page placeholder, EXCEPT when
    `strict` is set: then any read failure raises ConversionError. Strict mode is
    used for CBR, where a failed read usually means a broken/absent unrar tool
    (which would otherwise silently drop *every* page) rather than one bad file -
    critical because callers may delete the source after a "successful" convert."""
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
            print(f"  Warning: could not read '{name}': {e}")
            pages.append(Page(missing=True))
    return pages


def extract_from_cbz(path: Path, strict: bool = False) -> list[Page]:
    """Extract ordered Pages from a CBZ (ZIP) archive. Pass strict=True to raise
    on any unreadable page instead of silently inserting a missing placeholder
    (use for in-place rewrites where the source will be overwritten on success)."""
    try:
        with zipfile.ZipFile(path) as zf:
            return _extract_archive(zf.namelist(), zf.read, "CBZ", strict=strict)
    except zipfile.BadZipFile as e:
        raise ConversionError(f"could not open CBZ '{path.name}': {e}")


def extract_from_cbr(path: Path) -> list[Page]:
    """Extract ordered Pages from a CBR (RAR) archive. Needs rarfile + a working
    unrar tool. Verifies the tool up front and reads strictly, so a broken setup
    raises loudly instead of silently returning a short/empty page list (which,
    in the normalizer, would delete the source CBR after dropping pages)."""
    require(rarfile, "rarfile", "pip install rarfile  (and put unrar on PATH)")
    if not can_read_rar():
        raise ConversionError(
            "no RAR-reading tool found for CBR. Install 'unrar' (or 7-Zip), or "
            "set COMIC_UNRAR / pass --unrar to point at UnRAR.exe."
        )
    try:
        with rarfile.RarFile(path) as rf:
            return _extract_archive(rf.namelist(), rf.read, "CBR", strict=True)
    except rarfile.RarCannotExec as e:
        raise ConversionError(
            f"cannot run a RAR-reading tool (tried unrar='{UNRAR_TOOL}'): {e}. "
            "Set COMIC_UNRAR or pass --unrar to a working UnRAR executable."
        )
    except rarfile.Error as e:
        raise ConversionError(f"could not open CBR '{path.name}': {e}")


def extract_from_pdf(path: Path, dpi: int) -> list[Page]:
    """Rasterize each PDF page to an image Page at the given `dpi`. Needs
    PyMuPDF + Pillow; a page that fails to render becomes a missing placeholder."""
    require(fitz, "PyMuPDF", "pip install PyMuPDF")
    require(Image, "Pillow", "pip install Pillow")
    pages: list[Page] = []
    with fitz.open(str(path)) as doc:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for i, page in enumerate(doc):
            try:
                pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                pages.append(Page(image=img))
            except Exception as e:
                print(f"  Warning: could not render PDF page {i + 1}: {e}")
                pages.append(Page(missing=True))
    if not pages:
        raise ConversionError("PDF has no pages")
    return pages


def detect_format(path: Path) -> Optional[str]:
    """Identify the real container from its contents, ignoring the file
    extension: returns "cbz" (ZIP), "cbr" (RAR), "pdf", or None if unrecognized.
    Comic archives are frequently misnamed (a ZIP saved as .cbr, etc.), so
    dispatch trusts the content. Uses the archive libraries' own format checks
    (zipfile.is_zipfile / rarfile.is_rarfile) rather than hand-rolled magic."""
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


def extract_images(path: Path, pdf_dpi: int, strict_cbz: bool = False) -> list[Page]:
    """Dispatch to the right extractor by detecting the file's real container,
    falling back to the extension only when content is unrecognized. This
    tolerates misnamed archives - a ZIP saved as .cbr, a RAR saved as .cbz, etc.
    Raises ConversionError for anything unsupported. Pass strict_cbz=True to
    refuse on any unreadable CBZ page (use when the source will be overwritten)."""
    fmt = detect_format(path)
    if fmt is None:
        # Unrecognized content: fall back to the extension so a clear,
        # extension-appropriate error is raised (e.g. corrupt/truncated file).
        fmt = path.suffix.lower().lstrip(".")
    if fmt == "cbz":
        return extract_from_cbz(path, strict=strict_cbz)
    if fmt == "cbr":
        return extract_from_cbr(path)
    if fmt == "pdf":
        return extract_from_pdf(path, pdf_dpi)
    raise ConversionError(
        f"unsupported or unrecognized source format: '{path.name}'"
    )


def _read_extras(namelist, reader) -> dict[str, bytes]:
    """Collect {name: bytes} for root-level reader-metadata members to preserve
    (see METADATA_NAMES). Junk, nested, and unreadable members are skipped."""
    extras: dict[str, bytes] = {}
    for name in namelist:
        if _is_preservable_extra(name):
            try:
                extras[name] = reader(name)
            except Exception:
                pass
    return extras


def archive_extras(path: Path) -> dict[str, bytes]:
    """Return {name: bytes} for preservable reader-metadata (ComicInfo.xml) at
    the root of a CBZ/CBR, so an archive rewrite can carry it over. Dispatches by
    the real container (detected), tolerating misnamed archives."""
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


# ── Transforms ───────────────────────────────────────────────────────────────

def apply_transforms(
    pages: list[Page],
    drop_first: int,
    drop_last: int,
    fill_missing: Optional[str],
) -> list[Page]:
    """Apply page-level edits and return the final page list.

    Drops the first `drop_first` and last `drop_last` pages, then handles
    unreadable pages: replaced with a solid `fill_missing` ("white"/"black")
    filler at the resolution of the first good page, or dropped when
    `fill_missing` is None. Raises ConversionError if nothing remains."""
    total_before = len(pages)
    if drop_first:
        pages = pages[drop_first:]
    if drop_last:
        pages = pages[:-drop_last] if drop_last < len(pages) else []
    if not pages:
        raise ConversionError(
            f"no pages remain after dropping {drop_first} first and "
            f"{drop_last} last from {total_before} total"
        )

    result: list[Page] = []
    ref_size: Optional[tuple[int, int]] = None
    ref_resolved = False

    def reference_size() -> tuple[int, int]:
        # Decode a real page for its dimensions only when a filler is needed,
        # so all-passthrough conversions never require Pillow.
        nonlocal ref_size, ref_resolved
        if not ref_resolved:
            ref_resolved = True
            for q in pages:
                if not q.missing:
                    try:
                        ref_size = q.size()
                        break
                    except ConversionError:
                        pass
        return ref_size or (1275, 1755)  # ~US Letter @150dpi fallback

    for i, p in enumerate(pages):
        if p.missing:
            if fill_missing:
                print(f"  Replacing missing page {i + 1} with a {fill_missing} page.")
                result.append(blank_page(*reference_size(), fill_missing))
            else:
                print(f"  Dropping missing page {i + 1} (use --fill-missing to keep).")
        else:
            result.append(p)

    if not result:
        raise ConversionError("no valid pages to write")
    return result


# ── Writers ──────────────────────────────────────────────────────────────────

# Map a page's stored extension to the filetype hint PyMuPDF expects.
_FITZ_FILETYPE = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png"}


@contextmanager
def atomic_output(dest: Path):
    """Yield a temp Path in the same directory as `dest`; on success, atomically
    replace `dest` with it. On any error the temp file is removed and `dest` is
    left untouched (no truncated/corrupt output)."""
    if dest.is_dir():
        raise ConversionError(f"destination is a directory, not a file: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=dest.suffix + ".part")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_cbz(
    pages: list[Page],
    dest: Path,
    quality: int,
    extras: Optional[dict[str, bytes]] = None,
) -> None:
    """Write pages to a CBZ (ZIP) at `dest` with padded page names, atomically.
    `extras` (e.g. ComicInfo.xml) are added last and never shadow a page name."""
    total = len(pages)
    used_names = set()
    with atomic_output(dest) as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, p in enumerate(pages):
                data, ext = p.encoded(quality, frozenset(ARCHIVE_PASSTHROUGH_EXTS))
                name = page_name(i, total, ext)
                used_names.add(name.lower())
                zf.writestr(name, data)
            for name, data in (extras or {}).items():
                if name.lower() in used_names:
                    continue  # never shadow a page
                zf.writestr(name, data)
    print(f"  Wrote CBZ: {dest}")


def write_cbr(pages: list[Page], dest: Path, quality: int, extras=None) -> None:
    """Write pages to a CBR (RAR) at `dest` with padded page names. Requires a
    'rar' create tool - unrar/7-Zip cannot create RAR archives. Builds a scratch
    archive beside `dest` and swaps it in atomically only on success; `extras`
    are included."""
    if not RAR_TOOL:
        raise ConversionError(
            "CBR output needs the 'rar' create tool (WinRAR's Rar.exe or rarlab "
            "'rar'; unrar/7-Zip cannot create RAR). Install it, or set COMIC_RAR "
            "/ pass --rar. Download: https://www.rarlab.com/download.htm"
        )
    if dest.is_dir():
        raise ConversionError(f"destination is a directory, not a file: {dest}")
    total = len(pages)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        used_names = set()
        for i, p in enumerate(pages):
            data, ext = p.encoded(quality, frozenset(ARCHIVE_PASSTHROUGH_EXTS))
            name = page_name(i, total, ext)
            used_names.add(name.lower())
            (tmp_path / name).write_bytes(data)
        for name, data in (extras or {}).items():
            base = Path(name).name
            if base.lower() in used_names:
                continue  # never shadow a page (matches write_cbz)
            (tmp_path / base).write_bytes(data)
        # Build into a scratch archive beside dest (same filesystem, so the
        # final os.replace is atomic); only swap into place on success.
        fd, archive_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".rar.part")
        os.close(fd)
        archive = Path(archive_name)
        os.remove(archive)  # rar won't append to an existing/empty file
        try:
            cmd = [RAR_TOOL, "a", "-ep", "-m0", "-idq", str(archive), "*"]
            try:
                result = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True)
            except OSError as e:
                raise ConversionError(f"cannot run rar tool '{RAR_TOOL}': {e}")
            if result.returncode != 0 or not archive.exists():
                raise ConversionError(
                    f"rar failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            # Verify rar actually added every file: rar exits 0 even when some
            # files are skipped (e.g. locked by antivirus). Count members vs
            # expected to catch silent partial archives before replacing dest.
            expected = len(list(tmp_path.iterdir()))
            try:
                lresult = subprocess.run(
                    [RAR_TOOL, "l", "-idq", str(archive)],
                    capture_output=True, text=True,
                )
                actual = sum(1 for line in lresult.stdout.splitlines() if line.strip())
            except OSError:
                actual = expected  # can't verify; proceed
            if actual < expected:
                raise ConversionError(
                    f"rar archive has {actual} of {expected} expected files; "
                    "some pages may have been skipped (check for locked files)"
                )
            os.replace(archive, dest)
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
    print(f"  Wrote CBR: {dest}")


def write_pdf(pages: list[Page], dest: Path, quality: int, extras=None) -> None:
    """Write pages to a PDF at `dest`, atomically. Prefers img2pdf (embeds image
    bytes directly), falling back to PyMuPDF. `extras` are ignored - PDF has no
    place to carry sidecar metadata like ComicInfo.xml."""
    if img2pdf is not None:
        try:
            payload = [p.encoded(quality)[0] for p in pages]
            data = img2pdf.convert(payload)
        except Exception as e:
            raise ConversionError(f"img2pdf failed: {e}") from e
        with atomic_output(dest) as tmp:
            tmp.write_bytes(data)
    elif fitz is not None:
        with fitz.open() as doc:
            for p in pages:
                data, ext = p.encoded(quality)
                filetype = _FITZ_FILETYPE.get(ext, "jpg")
                with fitz.open(stream=data, filetype=filetype) as img_doc:
                    pdf_bytes = img_doc.convert_to_pdf()
                with fitz.open("pdf", pdf_bytes) as img_pdf:
                    doc.insert_pdf(img_pdf)
            with atomic_output(dest) as tmp:
                doc.save(str(tmp))
    else:
        raise ConversionError(
            "PDF output needs img2pdf or PyMuPDF: pip install img2pdf"
        )
    print(f"  Wrote PDF: {dest}")


def write_output(
    pages: list[Page],
    dest: Path,
    fmt: str,
    quality: int,
    extras: Optional[dict[str, bytes]] = None,
) -> None:
    """Dispatch to the writer for `fmt` ("cbz"/"cbr"/"pdf")."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "cbz":
        write_cbz(pages, dest, quality, extras)
    elif fmt == "cbr":
        write_cbr(pages, dest, quality, extras)
    elif fmt == "pdf":
        write_pdf(pages, dest, quality, extras)
    else:
        raise ConversionError(f"unknown output format: '{fmt}'")


# ── High-level conversion ────────────────────────────────────────────────────

def convert(
    src: Path,
    dst: Path,
    out_fmt: str,
    *,
    quality: int = 90,
    pdf_dpi: int = 150,
    drop_first: int = 0,
    drop_last: int = 0,
    fill_missing: Optional[str] = None,
    preserve_metadata: bool = True,
    strict_cbz: bool = False,
) -> int:
    """Convert `src` to `dst` in `out_fmt`. Returns the number of pages written.
    Preserves ComicInfo.xml when going archive -> archive (CBZ/CBR); PDF output
    cannot carry it. Raises ConversionError. Pass strict_cbz=True when src==dst
    (in-place rewrite) to refuse on any unreadable page rather than silently
    dropping it and overwriting the source with fewer pages."""
    src_fmt = detect_format(src) or src.suffix.lower().lstrip(".")
    pages = extract_images(src, pdf_dpi, strict_cbz=strict_cbz)
    pages = apply_transforms(pages, drop_first, drop_last, fill_missing)
    extras = None
    if preserve_metadata and out_fmt in {"cbz", "cbr"} and src_fmt in {"cbz", "cbr"}:
        extras = archive_extras(src)
    write_output(pages, dst, out_fmt, quality, extras)
    return len(pages)


def is_normalized_cbz(path: Path) -> bool:
    """True if `path` already satisfies the page-naming convention and needs no
    rewrite: a flat layout of padded page names (001.jpg in order) plus only
    root-level preservable metadata (ComicInfo.xml). Any junk member, nested
    page, or misnamed page means "not normalized" and the file is rewritten.

    Note: this checks naming, not encoding. A correctly-named non-JPEG/PNG page
    (e.g. 1.gif) is considered normalized and left as-is, rather than triggering
    a lossy transcode to JPEG - matching the tool's avoid-silent-data-loss stance."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except Exception:
        return False

    pages: list[str] = []
    for n in names:
        if _is_page_entry(n):
            if n != Path(n).name:
                return False  # page nested in a subdirectory
            pages.append(n)
        elif _is_preservable_extra(n):
            continue  # root-level sidecar that a repack would keep as-is
        else:
            return False  # junk, directory entry, or nested/unexpected member

    if not pages:
        return False
    ordered = sorted(pages, key=natural_key)
    total = len(ordered)
    for i, n in enumerate(ordered):
        ext = Path(n).suffix.lower()
        if n != page_name(i, total, ext):
            return False
    return True
