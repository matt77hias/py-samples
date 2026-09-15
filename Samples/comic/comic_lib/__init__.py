"""
Shared library for comic-book archive handling (CBR/CBZ/CBT/CB7/PDF).

Used by:
    comic_convert.py       - general format converter CLI
    calibre_normalize.py   - Calibre-library CBZ normalizer
    calibre_regen_cbz.py   - regenerate CBZ from PDF in a Calibre library
    comic_formats.py       - report image formats inside CBR/CBZ archives

Dependencies (all optional; each is only required for the paths that use it):
    pip install img2pdf numpy Pillow PyMuPDF rarfile
    # CBR input  needs the 'unrar' CLI on PATH
    # CBR output needs the 'rar'   CLI on PATH (https://www.rarlab.com/)
    # numpy      needed for --pdf-color-mode auto and Page.is_greyscale()

Lossless where possible: archive->archive and archive->PDF keep the original
JPEG/PNG bytes untouched. Re-encoding only happens for PDF input, blank filler
pages, or non-JPEG/PNG source images.
"""

# Re-export everything so `import comic_lib as cl; cl.X` keeps working.

from ._core import (
    ConversionError,
    require,
    rarfile,
    fitz,
    Image,
    img2pdf,
    np,
    py7zr,
    SUPPORTED_IMAGE_EXTS,
    SUPPORTED_INPUT_EXTS,
    PASSTHROUGH_EXTS,
    ARCHIVE_PASSTHROUGH_EXTS,
    _ZIP_STORED_EXTS,
    METADATA_NAMES,
)

from ._rar import (
    UNRAR_TOOL,
    RAR_TOOL,
    can_read_rar,
    set_rar_tools,
)

from .page import (
    Page,
    natural_key,
    page_name,
    blank_page,
)

from .extract import (
    is_junk,
    is_page_entry,
    is_preservable_extra,
    _extract_archive,
    extract_from_cbz,
    extract_from_cbr,
    extract_from_cbt,
    extract_from_cb7,
    extract_from_pdf,
    detect_format,
    extract_images,
    archive_extras,
)

from .transform import apply_transforms

from .write import (
    atomic_output,
    write_cbz,
    write_cbr,
    write_cbt,
    write_cb7,
    write_pdf,
    write_output,
)

from .convert import (
    convert,
    is_normalized_cbz,
)

__all__ = [
    "ConversionError", "require",
    "rarfile", "fitz", "Image", "img2pdf", "np", "py7zr",
    "SUPPORTED_IMAGE_EXTS", "SUPPORTED_INPUT_EXTS",
    "PASSTHROUGH_EXTS", "ARCHIVE_PASSTHROUGH_EXTS", "_ZIP_STORED_EXTS", "METADATA_NAMES",
    "UNRAR_TOOL", "RAR_TOOL", "can_read_rar", "set_rar_tools",
    "Page", "natural_key", "page_name", "blank_page",
    "is_junk", "is_page_entry", "is_preservable_extra", "_extract_archive",
    "extract_from_cbz", "extract_from_cbr", "extract_from_cbt", "extract_from_cb7",
    "extract_from_pdf", "detect_format", "extract_images", "archive_extras",
    "apply_transforms",
    "atomic_output", "write_cbz", "write_cbr", "write_cbt", "write_cb7",
    "write_pdf", "write_output",
    "convert", "is_normalized_cbz",
]
