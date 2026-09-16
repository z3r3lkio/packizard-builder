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
    "integrated_pkg.patch.xz.b64.part-04-01": "7a522ff42e46b3fdd47d0744aa2097c5673c44c9e3a4d409b411484fabaee976",
    "integrated_pkg.patch.xz.b64.part-04-02": "d6687401aaf01d5ba593a6e309d423678496e82ccacde99795007417ee36217e",
    "integrated_pkg.patch.xz.b64.part-04-03": "b67cbe65874fd6fa18f94c9a085835257db8aa1f4d5575f7fe5b29de00a09f82",
    "integrated_pkg.patch.xz.b64.part-04-04": "c9466ede53f3a947933c6860199de0477104651ca1c57627f319ca79c40c77a0",
    "integrated_pkg.patch.xz.b64.part-04-05": "6477d9c19d88b1ece7c7c7dd3e0c9b2c33b71300dab42d413c5ce01f151cdc15",
    "integrated_pkg.patch.xz.b64.part-04-06": "22579f4995c36325789813ecb221be55363a35f1a173dfd9c34db57704858f74",
    "integrated_pkg.patch.xz.b64.part-04-07": "a223d149adcd8a428922d125f798dbfb9c97fc14a4ccc6860f01e1d7d8378446",
    "integrated_pkg.patch.xz.b64.part-04-08": "a6963dcfeb48a06290b2f3e27911b7ad654d37471c9330fe22425c736f9dc183",
    "integrated_pkg.patch.xz.b64.part-05": "efd2144754079adb3b1dc584f67333c42a45548c87fb80dd9e08c313d38ca5af",
    "integrated_pkg.patch.xz.b64.part-06-01": "428f6d53d4702bb211d08ae38206eebd60e43a6c33dd8391fce08041060052aa",
    "integrated_pkg.patch.xz.b64.part-06-02": "086767e2da7b228c933065f794b22daf8b8ba4a141e7321cf72fd81892605652",
    "integrated_pkg.patch.xz.b64.part-06-03": "f0b3af67326af483342bfb6423dca131fe20e12e1adca64995cabceaf40ffc0a",
    "integrated_pkg.patch.xz.b64.part-06-04": "515760c9b48ce25a4f8793f2313ff50e7eaaf0443363f8ca0d2e73918882a039",
    "integrated_pkg.patch.xz.b64.part-06-05": "dde4d06278e3e117a01cf327c44723179ed8a93d992329b0614edbe08c38deae",
    "integrated_pkg.patch.xz.b64.part-06-06": "de8c0687e08a75d85782955418ef8e7c3994c316b3b2ca459941841e2c946ba7",
    "integrated_pkg.patch.xz.b64.part-06-07": "fb9e92bbebc3886f2750f837377601ac2044a3b6c7d956936d059dba6f6bd6a0",
    "integrated_pkg.patch.xz.b64.part-06-08": "6a2c395b55a99c49b36278d8f582941b38556debe90248f98e15d2be8fa39031",
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
    actual_files = sorted(p.name for p in root.glob("integrated_pkg.patch.xz.b64.part-*"))
    if actual_files != list(EXPECTED):
        raise SystemExit(f"overlay fragment set mismatch:\nexpected {list(EXPECTED)}\nactual   {actual_files}")
    for name, expected in EXPECTED.items():
        raw = (root / name).read_bytes()
        actual = sha256(raw)
        if actual != expected:
            raise SystemExit(f"overlay part hash mismatch: {name}\nexpected {expected}\nactual   {actual}")
        pieces.append(raw.decode("ascii").strip())
        print(f"OK {name} {actual}")

    packed = base64.b64decode("".join(pieces), validate=True)
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
