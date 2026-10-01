#!/usr/bin/env bash
set -euo pipefail
: "${PS5_PAYLOAD_SDK:?Set PS5_PAYLOAD_SDK to your ps5-payload-sdk path}"
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
make PS5_PAYLOAD_SDK="$PS5_PAYLOAD_SDK" all
mkdir -p out/packizard
sprx="$(find out -type f -name 'libSceAmpr.sprx' -print -quit || true)"
prx="$(find out -type f -name 'libSceAmpr.prx' -print -quit || true)"
[[ -n "$sprx" ]] || { echo "PS5 runtime build did not produce libSceAmpr.sprx" >&2; exit 1; }
cp -f "$sprx" out/packizard/libSceAmpr.sprx
if [[ -n "$prx" ]]; then cp -f "$prx" out/packizard/libSceAmpr.prx; fi
echo "Packizard PS5 Runtime: out/packizard/libSceAmpr.sprx"
