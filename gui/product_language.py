"""Product-facing terminology for the Packizard-owned engine.

Internal compatibility keys and on-disk format identifiers may retain legacy
names while they are needed for compatibility. This module only controls text
shown to users.
"""
from __future__ import annotations

_REPLACEMENTS = (
    ("Packizard · AMPR + LibProsperoPKG", "Packizard Engine · Compression + PKG"),
    ("AMPR/LZ4 compression", "Packizard compression"),
    ("LZ4/AMPR compression", "Packizard compression"),
    ("AMPR/LZ4", "Packizard Engine"),
    ("LZ4/AMPR", "Packizard Engine"),
    ("Skip LZ4 integrity check", "Skip Packizard Engine integrity check"),
    ("LZ4 integrity check", "Packizard Engine integrity check"),
    ("LZ4 compression", "Packizard compression"),
    ("LZ4 Compression", "Packizard Compression"),
    ("LZ4 verification", "Engine verification"),
    ("Create PKG after LZ4 compression", "Create PKG after Packizard compression"),
    ("compressed AMPR output", "Packizard Engine output"),
    ("AMPR output", "Packizard Engine output"),
    ("TOML profiles folder", "Packizard profiles folder"),
    ("TOML profiles", "Packizard profiles"),
    ("Pack config", "Packizard profile"),
    ("LZ4", "Packizard codec"),
    ("AMPR", "Packizard Engine"),
)


def product_text(value: str) -> str:
    text = str(value)
    for old, new in _REPLACEMENTS:
        text = text.replace(old, new)
    return text


def _replace_property(widget, getter_name: str, setter_name: str) -> None:
    getter = getattr(widget, getter_name, None)
    setter = getattr(widget, setter_name, None)
    if not callable(getter) or not callable(setter):
        return
    try:
        current = getter()
    except TypeError:
        return
    if isinstance(current, str):
        updated = product_text(current)
        if updated != current:
            setter(updated)


def apply_product_language(root) -> None:
    """Normalize all product-facing text below *root* in one pass."""
    try:
        from PySide6.QtWidgets import QComboBox, QWidget
    except ImportError:
        return

    widgets = [root]
    if hasattr(root, "findChildren"):
        widgets.extend(root.findChildren(QWidget))

    for widget in widgets:
        for getter, setter in (
            ("text", "setText"),
            ("title", "setTitle"),
            ("toolTip", "setToolTip"),
            ("statusTip", "setStatusTip"),
            ("whatsThis", "setWhatsThis"),
            ("placeholderText", "setPlaceholderText"),
            ("accessibleName", "setAccessibleName"),
            ("accessibleDescription", "setAccessibleDescription"),
        ):
            _replace_property(widget, getter, setter)

        if isinstance(widget, QComboBox):
            for index in range(widget.count()):
                current = widget.itemText(index)
                updated = product_text(current)
                if updated != current:
                    widget.setItemText(index, updated)
