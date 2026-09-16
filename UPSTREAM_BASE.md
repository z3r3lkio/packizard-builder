# Upstream base

Packizard Builder 0.1.1 is derived from the user-supplied `Lazy_AMPR-0.0.1.zip`.

The corresponding public Lazy_AMPR baseline is:

- Repository: https://github.com/Nazky/Lazy_AMPR
- Commit: `033a85bf2cbc343ed8da81dcef55faac8ba7628a` (`first push`)
- Version: `0.0.1`

The Packizard-specific PKG integration is now a launcher for the external **PPR-PKG Builder / LibProsperoPkg.Gui** application. The previous direct `core/prospero_pkg.py` bridge, native-engine downloader and internal PKG worker were removed so package generation cannot silently use a different implementation.

The full source snapshot also contains the reworked PySide6 UI, Packizard branding, build scripts, state migration, tests and original AMPR tool tree.
