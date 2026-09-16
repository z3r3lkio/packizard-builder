#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import lzma
from pathlib import Path

EXPECTED = {
    "integrated_pkg.patch.xz.b64.part-01": "e9030c46f5c3b386613fb612d67e16462bb6a2bdf439cd3bc5602d2a06624d7c",
    "integrated_pkg.patch.xz.b64.part-02": "b41e2df7f99e756951d66b49f4b8714d8777c8d6d0773dc1ccce4fe45c9e74f2",
    "integrated_pkg.patch.xz.b64.part-03": "36b0d5553029c50cae110a2dfde224651d80f20f0eb41efa99ad45a94c1e062b",
    "integrated_pkg.patch.xz.b64.part-04": "e20c2db3a6c80f59a48e05f25843ec67ddbea5be8c41d10a85c2e23e8957de27",
    "integrated_pkg.patch.xz.b64.part-05": "efd2144754079adb3b1dc584f67333c42a45548c87fb80dd9e08c313d38ca5af",
    "integrated_pkg.patch.xz.b64.part-06": "ebe7a325e0c8919c3b3a26298e27580d9bf115dfc0406e6537090f0c751841bf",
    "integrated_pkg.patch.xz.b64.part-07": "81802c3810d3d915bba47c53ead66ab942748d3c3ad0c42f252629cbec4d7531",
    "integrated_pkg.patch.xz.b64.part-08": "3cbd7a794b85f81d28658bc411b926f0805f44e6e30bcf222740cc9e710b1691",
    "integrated_pkg.patch.xz.b64.part-09": "e1e8ec996d44d012bbe484b5983fe1648131358aa1a05c56386ca645280e0f03",
    "integrated_pkg.patch.xz.b64.part-10": "6e9badf4d9b678e6d6a7074f2d5e279a7ac8429404574479225840d0df4026d3",
    "integrated_pkg.patch.xz.b64.part-11": "97b0ea825f31c3cd4f7bb43291479f8b80fb735369682c59e9b8c3a95206d37c",
}
EXPECTED_XZ = "f37a7ad30dc2ec3286a085f31039af8920cde1d811f6e80f42bd2880e4079564"
EXPECTED_PATCH = "795c8a14474aabbbf2f202f72ca42118ad103dd12b2a105318b03d03ae968fa1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parent
    pieces: list[str] = []
    for name, expected in EXPECTED.items():
        path = root / name
        if not path.is_file():
            raise SystemExit(f"missing overlay part: {name}")
        raw = path.read_bytes()
        actual = sha256(raw)
        if actual != expected:
            raise SystemExit(f"overlay part hash mismatch: {name}\nexpected {expected}\nactual   {actual}")
        pieces.append(raw.decode("ascii").strip())
        print(f"OK {name} {actual}")

    encoded = "".join(pieces)
    packed = base64.b64decode(encoded, validate=True)
    packed_hash = sha256(packed)
    if packed_hash != EXPECTED_XZ:
        raise SystemExit(f"XZ payload hash mismatch: {packed_hash}")
    patch = lzma.decompress(packed)
    patch_hash = sha256(patch)
    if patch_hash != EXPECTED_PATCH:
        raise SystemExit(f"patch hash mismatch: {patch_hash}")
    print(f"OK XZ {packed_hash}")
    print(f"OK patch {patch_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
