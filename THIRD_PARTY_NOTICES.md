# Third-party notices

Packizard Builder is an integration layer over components with their own licenses. Review and comply with each upstream license before distributing a binary.

- **Lazy_AMPR / AMPR workflow** — the uploaded base application includes `external/ampr_emu`, credited to Drakmor and distributed under GPL-3.0 in the supplied source tree.
- **PPR-PKG Builder / LibProsperoPkg.Gui** — external application selected and launched by the user for PKG creation. Packizard does not redistribute the executable, does not copy its package implementation, and does not fall back to an internal PKG builder.
- **LZ4** — license retained from the supplied source tree under `external/ampr_emu/third_party/lz4/LICENSE`.
- **PySide6 / Qt for Python** — runtime dependency; consult Qt/PySide licensing for the distribution model you choose.

Upstream references:

- https://github.com/drakmor/ampr_emu
- https://github.com/drakmor/ppr-patch
- https://github.com/drakmor/LibProsperoPKG
- https://github.com/SvenGDK/LibProsperoPKG
