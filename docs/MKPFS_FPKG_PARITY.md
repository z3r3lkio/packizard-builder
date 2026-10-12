# MkPFS.CSharp FPKG parity track

Pinned oracle: `danthespal/MkPFS.CSharp@dfca7367897a38f9ad425172f6f4f3f84b40d0c4`.

Packizard uses MkPFS.CSharp as a public behavioral/structural oracle for the PS5 debug-package pipeline. The target architecture is:

1. data-first inner image;
2. `naps_pkg_layout.dat`;
3. outer PFS with SHA3 block signatures and superblock ICV;
4. AES-XTS outer-image encryption using the package image key and 16-byte seed;
5. `imagedigs.dat` from plaintext outer-PFS blocks;
6. CNT, FIH and SI finalized from the same image geometry and digests.

The previous Packizard "Standard" experiment that replaced the inner image with a conventional superblock-first PFS wrapped in PFSC is intentionally retired. The pinned LibProsperoPKG builder already contains the same data-first/NAPS/outer-PFS architecture that MkPFS.CSharp validates against PS5PkgTool.

## Parity policy

For deterministic stored-mode fixtures, compare geometry and metadata first, then byte-level output where random RSA padding is normalized. For compressed/Kraken fixtures, require structural parity: identical logical chunk boundaries, compress/store decisions, NAPS geometry, outer-PFS block geometry, CNT inventory and FIH/SI relationships.

Do not use private SDK keys or proprietary signing material as part of the oracle. Package keys are derived only from user-supplied debug-package inputs already supported by Packizard.
