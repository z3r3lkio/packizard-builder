from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
# Packizard uses PNG artwork and does not consume Qt's TIFF image plugin.
# PySide6's Linux libqtiff plugin still links against libtiff.so.5, which is
# no longer shipped by Ubuntu 24.04 (Noble). Exclude only that optional plugin
# rather than fabricating an ABI-unsafe libtiff.so.5 -> libtiff.so.6 symlink.
binaries = [entry for entry in binaries if Path(entry[0]).name != "libqtiff.so"]
