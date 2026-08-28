"""Core: exception, helpers, constants, and all optional imports."""

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

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
SUPPORTED_INPUT_EXTS = {".cbr", ".cbz", ".pdf"}
PASSTHROUGH_EXTS = {".jpg", ".jpeg", ".png"}
ARCHIVE_PASSTHROUGH_EXTS = PASSTHROUGH_EXTS | {".webp"}
_ZIP_STORED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
METADATA_NAMES = {"comicinfo.xml"}


# ── Exception & require ───────────────────────────────────────────────────────

class ConversionError(Exception):
    """Raised for a single-file failure so batch callers can continue."""


def require(module, name: str, hint: str) -> None:
    """Raise ConversionError if an optional dependency `module` is None."""
    if module is None:
        raise ConversionError(f"Missing dependency '{name}'. Install with: {hint}")
