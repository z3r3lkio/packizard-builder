# Packizard Builder 0.2.0 candidate

UAT candidate highlights:

- PKG builds are integrated into Packizard; no external PPR-PKG Builder window is launched.
- Compress can automatically continue into PKG creation after successful LZ4/AMPR processing.
- Build PKG remains available as an integrated advanced/manual path.
- Packizard.PkgBridge is built for each release architecture against the pinned public LibProsperoPKG source.
- Large PS5 package builds now switch to disk-backed inner/outer PFS assembly instead of allocating the complete image in a single CLR byte array, removing the previous ~2 GiB overflow path.
- PPR-PKG Builder/fpkg-gui 0.6.8 is the current behavior reference and is versioned independently from the public source engine.
- Complete Packizard lizard branding is restored at higher resolution.
- Credits identify Packizard as the integration application and keep upstream thanks compact.
