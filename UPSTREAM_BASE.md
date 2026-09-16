# Upstream base

The Packizard Builder 0.1.0 source snapshot was derived from the user-supplied `Lazy_AMPR-0.0.1.zip`.

The corresponding public Lazy_AMPR source baseline is:

- Repository: https://github.com/Nazky/Lazy_AMPR
- Commit: `033a85bf2cbc343ed8da81dcef55faac8ba7628a` (`first push`)
- Version in that baseline: `0.0.1`

Packizard-specific PKG integration is implemented in `core/prospero_pkg.py`; the official native engine is fetched by `scripts/fetch_pkg_engine.py`.

The complete 0.1.0 source snapshot also contains the reworked PySide6 UI, Packizard branding assets, build scripts, state migration, tests, and the original AMPR tool tree. Keep the upstream AMPR and LibProsperoPkg license notices when redistributing a binary.
