from __future__ import annotations

from pathlib import Path

FIH_BUILDER_RELATIVE = Path("src/LibProsperoPkg/PKG/ProsperoFihBuilder.cs")

_DOC_ORIGINAL = """    /// <param name=\"nwonlyAppFileCount\">Application-payload file count for the FIH file-count field.</param>\n    /// <param name=\"siArchivePathFactory\">Optional file-backed SI factory for large finalized mount images.</param>\n"""

_DOC_PATCHED = """    /// <param name=\"nwonlyAppFileCount\">Application-payload file count for the FIH file-count field.</param>\n    /// <param name=\"nwonlyNdblock\">Inner nwonly logical mount size expressed as a 64 KiB block count; 0 when not available.</param>\n    /// <param name=\"siArchivePathFactory\">Optional file-backed SI factory for large finalized mount images.</param>\n"""


def apply_warning_cleanup(vendor_dir: str | Path) -> bool:
    """Keep Packizard-added LibProspero public parameters warning-free under XML-doc builds."""
    path = Path(vendor_dir) / FIH_BUILDER_RELATIVE
    if not path.is_file():
        raise RuntimeError(f"LibProsperoPKG FIH builder is missing: {path}")
    text = path.read_text(encoding="utf-8")
    if _DOC_PATCHED in text:
        return False
    if _DOC_ORIGINAL not in text:
        raise RuntimeError("Pinned LibProsperoPKG FIH XML-doc preimage changed; review warning cleanup.")
    path.write_text(text.replace(_DOC_ORIGINAL, _DOC_PATCHED, 1), encoding="utf-8")
    return True
