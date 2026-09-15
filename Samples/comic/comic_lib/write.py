"""Archive and PDF writers."""

import io
import os
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from ._core import (
    ConversionError, require,
    fitz, img2pdf, py7zr,
    ARCHIVE_PASSTHROUGH_EXTS, _ZIP_STORED_EXTS,
)
from ._rar import RAR_TOOL
from .page import Page, page_name

_ARCHIVE_PASSTHROUGH = frozenset(ARCHIVE_PASSTHROUGH_EXTS)
_ZIP_STORED = frozenset(_ZIP_STORED_EXTS)

_FITZ_FILETYPE = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png"}


@contextmanager
def atomic_output(dest: Path):
    """Yield a temp Path; on success atomically replace dest with it."""
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
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Write pages to a CBZ (ZIP) at dest with padded page names, atomically."""
    total = len(pages)
    used_names = set()
    with atomic_output(dest) as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i, p in enumerate(pages):
                data, ext = p.encoded(quality, _ARCHIVE_PASSTHROUGH, image_format)
                name = page_name(i, total, ext)
                used_names.add(name.lower())
                compression = (zipfile.ZIP_STORED if ext in _ZIP_STORED
                               else zipfile.ZIP_DEFLATED)
                zf.writestr(name, data, compress_type=compression)
            for name, data in (extras or {}).items():
                if name.lower() in used_names:
                    continue
                zf.writestr(name, data)
    log(f"  Wrote CBZ: {dest}")


def write_cbr(
    pages: list[Page],
    dest: Path,
    quality: int,
    extras=None,
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Write pages to a CBR (RAR) at dest. Requires the 'rar' create tool."""
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
            data, ext = p.encoded(quality, _ARCHIVE_PASSTHROUGH, image_format)
            name = page_name(i, total, ext)
            used_names.add(name.lower())
            (tmp_path / name).write_bytes(data)
        for name, data in (extras or {}).items():
            base = Path(name).name
            if base.lower() in used_names:
                continue
            (tmp_path / base).write_bytes(data)
        fd, archive_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".rar.part")
        os.close(fd)
        archive = Path(archive_name)
        os.remove(archive)
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
            expected = len(list(tmp_path.iterdir()))
            try:
                lresult = subprocess.run(
                    [RAR_TOOL, "l", "-idq", str(archive)],
                    capture_output=True, text=True,
                )
                actual = sum(1 for line in lresult.stdout.splitlines() if line.strip())
            except OSError:
                actual = expected
            if actual < expected:
                raise ConversionError(
                    f"rar archive has {actual} of {expected} expected files; "
                    "some pages may have been skipped (check for locked files)"
                )
            os.replace(archive, dest)
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
    log(f"  Wrote CBR: {dest}")


def write_cbt(
    pages: list[Page],
    dest: Path,
    quality: int,
    extras: Optional[dict[str, bytes]] = None,
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Write pages to a CBT (TAR) at dest with padded page names, atomically."""
    total = len(pages)
    used_names: set[str] = set()
    with atomic_output(dest) as tmp:
        with tarfile.open(tmp, "w") as tf:
            for i, p in enumerate(pages):
                data, ext = p.encoded(quality, _ARCHIVE_PASSTHROUGH, image_format)
                name = page_name(i, total, ext)
                used_names.add(name.lower())
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            for name, data in (extras or {}).items():
                base = Path(name).name
                if base.lower() in used_names:
                    continue
                info = tarfile.TarInfo(name=base)
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    log(f"  Wrote CBT: {dest}")


def write_cb7(
    pages: list[Page],
    dest: Path,
    quality: int,
    extras: Optional[dict[str, bytes]] = None,
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Write pages to a CB7 (7-Zip) at dest with padded page names, atomically."""
    require(py7zr, "py7zr", "pip install py7zr")
    total = len(pages)
    used_names: set[str] = set()
    with atomic_output(dest) as tmp:
        with py7zr.SevenZipFile(tmp, mode="w") as zf:
            for i, p in enumerate(pages):
                data, ext = p.encoded(quality, _ARCHIVE_PASSTHROUGH, image_format)
                name = page_name(i, total, ext)
                used_names.add(name.lower())
                zf.writef(io.BytesIO(data), name)
            for name, data in (extras or {}).items():
                base = Path(name).name
                if base.lower() in used_names:
                    continue
                zf.writef(io.BytesIO(data), base)
    log(f"  Wrote CB7: {dest}")


def write_pdf(
    pages: list[Page],
    dest: Path,
    quality: int,
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Write pages to a PDF at dest, atomically. Prefers img2pdf, falls back to PyMuPDF."""
    pdf_image_fmt = image_format if image_format in ("jpeg", "png") else "jpeg"
    if img2pdf is not None:
        try:
            payload = [p.encoded(quality, image_format=pdf_image_fmt)[0] for p in pages]
            data = img2pdf.convert(payload)
        except Exception as e:
            raise ConversionError(f"img2pdf failed: {e}") from e
        with atomic_output(dest) as tmp:
            tmp.write_bytes(data)
    elif fitz is not None:
        with fitz.open() as doc:
            for p in pages:
                data, ext = p.encoded(quality, image_format=pdf_image_fmt)
                filetype = _FITZ_FILETYPE.get(ext, "jpg")
                with fitz.open(stream=data, filetype=filetype) as img_doc:
                    pdf_bytes = img_doc.convert_to_pdf()
                with fitz.open("pdf", pdf_bytes) as img_pdf:
                    doc.insert_pdf(img_pdf)
            with atomic_output(dest) as tmp:
                doc.save(str(tmp))
    else:
        raise ConversionError("PDF output needs img2pdf or PyMuPDF: pip install img2pdf")
    log(f"  Wrote PDF: {dest}")


def write_output(
    pages: list[Page],
    dest: Path,
    fmt: str,
    quality: int,
    extras: Optional[dict[str, bytes]] = None,
    image_format: str = "jpeg",
    log=print,
) -> None:
    """Dispatch to the writer for fmt ("cbz"/"cbr"/"pdf")."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "cbz":
        write_cbz(pages, dest, quality, extras, image_format, log)
    elif fmt == "cbr":
        write_cbr(pages, dest, quality, extras, image_format, log)
    elif fmt == "cbt":
        write_cbt(pages, dest, quality, extras, image_format, log)
    elif fmt == "cb7":
        write_cb7(pages, dest, quality, extras, image_format, log)
    elif fmt == "pdf":
        write_pdf(pages, dest, quality, image_format, log)
    else:
        raise ConversionError(f"unknown output format: '{fmt}'")
