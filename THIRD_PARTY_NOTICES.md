# Third-party notices

Packizard Builder is an integration layer over components with their own licenses. Before distributing a binary, review and comply with each upstream license and include the corresponding source/license notices.

- **Lazy_AMPR / AMPR workflow** — the uploaded base application includes `external/ampr_emu`, credited to Drakmor and distributed under GPL-3.0 in the supplied source tree.
- **LibProsperoPKG** — SvenGDK, GPL-3.0-or-later. Packizard's PKG page talks to its published C ABI and the fetch script downloads official release artifacts without modifying them.
- **LZ4** — license retained from the supplied source tree under `external/ampr_emu/third_party/lz4/LICENSE`.
- **PySide6 / Qt for Python** — runtime dependency; consult Qt/PySide licensing for the distribution model you choose.

Upstream references:

- https://github.com/Nazky/Lazy_AMPR
- https://github.com/drakmor/ampr_emu
- https://github.com/SvenGDK/LibProsperoPKG
- https://github.com/SvenGDK/LibProsperoPKG/releases/tag/v2.5
