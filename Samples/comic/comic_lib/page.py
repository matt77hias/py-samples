"""Page model and page-level helpers."""

import io
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from ._core import (
    ConversionError, require, Image, np,
    PASSTHROUGH_EXTS,
)

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


class Page:
    """A single comic page, carrying original encoded bytes when available so
    conversions can avoid re-encoding."""

    __slots__ = ("data", "ext", "_image", "missing")

    def __init__(self, data=None, ext=None, image=None, missing=False):
        self.data: Optional[bytes] = data
        self.ext: Optional[str] = ext.lower() if ext else None
        self._image: Optional["PILImage"] = image
        self.missing: bool = missing

    def pil(self) -> "PILImage":
        """Decode to a PIL image (cached). L-mode and RGB are returned as-is;
        any other mode is normalised to RGB."""
        if self._image is None:
            if self.data is None:
                raise ConversionError("page has no data to decode")
            require(Image, "Pillow", "pip install Pillow")
            img = Image.open(io.BytesIO(self.data))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.load()
            self._image = img
        elif self._image.mode not in ("RGB", "L"):
            self._image = self._image.convert("RGB")
        return self._image

    def is_greyscale(self) -> bool:
        """Return True when the decoded image is greyscale (all channels equal)."""
        try:
            require(Image, "Pillow", "pip install Pillow")
            img = self.pil()
            if img.mode == "L":
                return True
            if img.mode == "RGB":
                require(np, "numpy", "pip install numpy")
                arr = np.asarray(img)
                return bool((arr[:, :, 0] == arr[:, :, 1]).all() and
                            (arr[:, :, 1] == arr[:, :, 2]).all())
        except Exception:
            pass
        return False

    def image_info(self) -> "Optional[tuple[tuple[int, int], str]]":
        """Return (size, mode) without fully decoding the image, or None.

        Uses the already-decoded bitmap when available; otherwise does a
        header-only open of the raw bytes (cheap — no pixel data decoded)."""
        if self._image is not None:
            return self._image.size, self._image.mode
        if self.data is not None:
            require(Image, "Pillow", "pip install Pillow")
            try:
                img = Image.open(io.BytesIO(self.data))
                return img.size, img.mode
            except Exception:
                return None
        return None

    def release(self) -> None:
        """Drop the decoded bitmap and raw bytes to free memory after encoding."""
        self._image = None
        self.data = None

    def encoded(
        self,
        quality: int,
        passthrough_exts: frozenset[str] = frozenset(PASSTHROUGH_EXTS),
        image_format: str = "jpeg",
    ) -> tuple[bytes, str]:
        """Return (bytes, extension) ready to store."""
        if self.data is not None and self.ext in passthrough_exts:
            return self.data, self.ext
        fmt_map = {"jpeg": ("JPEG", ".jpg"), "png": ("PNG", ".png"), "webp": ("WEBP", ".webp")}
        pil_fmt, ext = fmt_map.get(image_format, ("JPEG", ".jpg"))
        img = self.pil()
        buf = io.BytesIO()
        if pil_fmt == "JPEG":
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            img.save(buf, format="JPEG", quality=quality, optimize=True)
        elif pil_fmt == "PNG":
            if img.mode not in ("L", "RGB", "RGBA"):
                img = img.convert("RGB")
            img.save(buf, format="PNG", optimize=True)
        else:  # WEBP
            # Pillow's WebP encoder silently promotes L to RGB on save; convert
            # explicitly so the round-trip mode is predictable (always RGB/RGBA).
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            img.save(buf, format="WEBP", quality=quality, method=4)
        return buf.getvalue(), ext


def natural_key(s: str):
    """Sort key so page2 < page10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def page_name(index: int, total: int, ext: str = ".jpg") -> str:
    """Zero-padded page filename."""
    digits = max(1, len(str(total)))
    return f"{index + 1:0{digits}d}{ext}"


def blank_page(width: int, height: int, color: str, mode: str = "RGB") -> Page:
    """Build a solid white or black filler page matching the given colour mode."""
    require(Image, "Pillow", "pip install Pillow")
    value = (255, 255, 255) if color == "white" else (0, 0, 0)
    pixel = value[0] if mode == "L" else value
    return Page(image=Image.new(mode, (width, height), pixel))
