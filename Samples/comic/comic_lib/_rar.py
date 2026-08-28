"""RAR tool detection and management."""

import os
import shutil
from pathlib import Path
from typing import Optional

from ._core import rarfile, ConversionError, require


def _probe_tool(names: tuple[str, ...], env_var: str) -> Optional[str]:
    """Find an executable by env var override, then PATH, then known install
    dirs. Returns an absolute path or a bare command name, else None."""
    override = os.environ.get(env_var)
    if override:
        return override
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


UNRAR_TOOL: Optional[str] = _probe_tool(("unrar", "UnRAR.exe", "unrar.exe"), "COMIC_UNRAR")
RAR_TOOL: Optional[str] = _probe_tool(("rar", "Rar.exe", "rar.exe"), "COMIC_RAR")

if rarfile is not None and UNRAR_TOOL:
    rarfile.UNRAR_TOOL = UNRAR_TOOL


def can_read_rar() -> bool:
    """True if some RAR-reading backend is available."""
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
    """Override the detected rar (create) and/or unrar (extract) tool paths."""
    global RAR_TOOL, UNRAR_TOOL
    if rar:
        RAR_TOOL = rar
    if unrar:
        UNRAR_TOOL = unrar
        if rarfile is not None:
            rarfile.UNRAR_TOOL = unrar
