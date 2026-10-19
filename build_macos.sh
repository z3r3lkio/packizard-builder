#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
parent_dir="$(dirname -- "$project_dir")"
bootstrap_python="${PYTHON:-python3}"
version="$(cd -- "$project_dir" && "$bootstrap_python" -c 'from version import VERSION; print(VERSION)' 2>/dev/null || true)"
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+)?$ ]]; then
    echo "Invalid application version: ${version:-unavailable}" >&2
    exit 1
fi

machine="$(uname -m)"
case "$machine" in
    x86_64) arch="x64"; expected_macho_arch="x86_64" ;;
    arm64) arch="arm64"; expected_macho_arch="arm64" ;;
    *) echo "Unsupported macOS architecture: $machine" >&2; exit 2 ;;
esac

release_base="$parent_dir/release"
release_root="${1:-$release_base/$version-macos-$arch}"
mkdir -p "$release_base"
release_base="$(cd "$release_base" && pwd)"
mkdir -p "$release_root"
release_root="$(cd "$release_root" && pwd)"
if [[ "$(dirname "$release_root")" != "$release_base" ]]; then
    echo "Refusing to clean unexpected release path: $release_root" >&2
    exit 1
fi

build_venv="${PACKIZARD_BUILD_VENV:-$project_dir/.venv-macos-$arch}"
if [[ ! -x "$build_venv/bin/python" ]]; then
    "$bootstrap_python" -m venv "$build_venv"
    "$build_venv/bin/python" -m pip install --upgrade pip
    "$build_venv/bin/python" -m pip install -r "$project_dir/requirements-build.txt"
fi
python="$build_venv/bin/python"

rm -rf "$release_root"
mkdir -p "$release_root/work" "$release_root/dist"
cd "$project_dir"

"$python" -m PyInstaller --noconfirm --clean --workpath "$release_root/work" --distpath "$release_root/dist" Packizard_Builder.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$release_root/work" --distpath "$release_root/dist" Packizard_Packer_Worker.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$release_root/work" --distpath "$release_root/dist" Packizard_Profile_Worker.spec

app="$release_root/dist/Packizard Builder.app"
if [[ ! -d "$app" ]]; then
    echo "PyInstaller did not produce the expected macOS app bundle: $app" >&2
    exit 3
fi

mkdir -p "$app/Contents/MacOS/workers/Packizard-Packer-Worker" "$app/Contents/MacOS/workers/Packizard-Profile-Worker"
cp -a "$release_root/dist/Packizard-Packer-Worker" "$app/Contents/MacOS/workers/Packizard-Packer-Worker/Packizard-Packer-Worker"
cp -a "$release_root/dist/Packizard-Profile-Worker" "$app/Contents/MacOS/workers/Packizard-Profile-Worker/Packizard-Profile-Worker"

"$python" scripts/prepare_pkg_bridge.py --rid "osx-$arch"
mkdir -p "$app/Contents/MacOS/pkg_bridge"
cp -a "pkg_bridge/osx-$arch/." "$app/Contents/MacOS/pkg_bridge/"
mkdir -p "$app/Contents/Resources/licenses/LibProsperoPKG"
cp "vendor/LibProsperoPKG/LICENSE" "$app/Contents/Resources/licenses/LibProsperoPKG/LICENSE"

chmod +x "$app/Contents/MacOS/Packizard_Builder" \
    "$app/Contents/MacOS/workers/Packizard-Packer-Worker/Packizard-Packer-Worker" \
    "$app/Contents/MacOS/workers/Packizard-Profile-Worker/Packizard-Profile-Worker" \
    "$app/Contents/MacOS/pkg_bridge/Packizard.PkgBridge"

# .NET publish emits XML/PDB documentation next to the executable. They are not
# required at runtime and previously confused the nested-code signing pass when
# the bridge was injected under Contents/MacOS.
find "$app/Contents/MacOS/pkg_bridge" -type f \( -name '*.xml' -o -name '*.pdb' \) -delete

# PyInstaller signs the original bundle before Packizard injects workers and the
# .NET bridge. Any subsequent modification invalidates that container seal and
# macOS can report the downloaded app as damaged. Clear stale signatures and
# sign the FINAL bundle after every payload has been installed.
xattr -cr "$app"
rm -rf -- "$app/Contents/_CodeSignature"

codesign_identity="${PACKIZARD_CODESIGN_IDENTITY:--}"
codesign_args=(--force --deep --sign "$codesign_identity")
if [[ "$codesign_identity" != "-" ]]; then
    codesign_args+=(--options runtime --timestamp)
fi
codesign "${codesign_args[@]}" "$app"

# CI must reject an internally inconsistent bundle instead of publishing an app
# that Gatekeeper later calls corrupt/damaged.
codesign --verify --deep --strict --verbose=2 "$app"

# Ensure the produced package actually contains the native executable expected
# by the matrix entry (especially important for Apple Silicon / M4 machines).
for exe in \
    "$app/Contents/MacOS/Packizard_Builder" \
    "$app/Contents/MacOS/workers/Packizard-Packer-Worker/Packizard-Packer-Worker" \
    "$app/Contents/MacOS/workers/Packizard-Profile-Worker/Packizard-Profile-Worker" \
    "$app/Contents/MacOS/pkg_bridge/Packizard.PkgBridge"; do
    arches="$(lipo -archs "$exe" 2>/dev/null || true)"
    if [[ " $arches " != *" $expected_macho_arch "* ]]; then
        echo "Unexpected architecture for $exe: ${arches:-not a Mach-O executable}; expected $expected_macho_arch" >&2
        exit 4
    fi
done

zip_path="$release_root/Packizard-Builder-$version-macOS-$arch.zip"
portable="$release_root/Packizard-Builder-$version-macOS-$arch.tar.gz"
ditto -c -k --sequesterRsrc --keepParent "$app" "$zip_path"
tar -C "$release_root/dist" -czf "$portable" "Packizard Builder.app"
(
    cd "$release_root"
    shasum -a 256 "$(basename "$zip_path")" "$(basename "$portable")" > "SHA256SUMS-macOS-$arch.txt"
)
echo "Built $zip_path"
echo "Built $portable"
cat "$release_root/SHA256SUMS-macOS-$arch.txt"
