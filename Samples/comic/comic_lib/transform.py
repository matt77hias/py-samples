"""Page-level transforms: drop, fill-missing."""

from typing import Optional

from ._core import ConversionError
from .page import Page, blank_page


def apply_transforms(
    pages: list[Page],
    drop_first: int,
    drop_last: int,
    fill_missing: Optional[str],
    log=print,
) -> list[Page]:
    """Apply page-level edits and return the final page list."""
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
    ref_mode: str = "RGB"
    ref_resolved = False

    def reference_props() -> tuple[tuple[int, int], str]:
        nonlocal ref_size, ref_mode, ref_resolved
        if not ref_resolved:
            ref_resolved = True
            for q in pages:
                if not q.missing:
                    info = q.image_info()
                    if info is None:
                        continue
                    ref_size, ref_mode = info
                    # A header-only decode can report palette/CMYK/etc modes
                    # (e.g. "P" for GIFs); blank_page only supports L/RGB, so
                    # clamp anything exotic to RGB — matching Page.pil().
                    if ref_mode not in ("RGB", "L"):
                        ref_mode = "RGB"
                    break
        return ref_size or (1275, 1755), ref_mode

    for i, p in enumerate(pages):
        if p.missing:
            if fill_missing:
                log(f"  Replacing missing page {i + 1} with a {fill_missing} page.")
                size, mode = reference_props()
                result.append(blank_page(*size, fill_missing, mode))
            else:
                log(f"  Dropping missing page {i + 1} (use --fill-missing to keep).")
        else:
            result.append(p)

    if not result:
        raise ConversionError("no valid pages to write")
    return result
