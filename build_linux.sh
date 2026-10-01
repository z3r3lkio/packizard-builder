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
    x86_64|amd64) arch="x64"; appimage_arch="x86_64" ;;
    aarch64|arm64) arch="arm64"; appimage_arch="aarch64" ;;
    *) echo "Unsupported Linux architecture: $machine" >&2; exit 2 ;;
esac

release_base="$(realpath -m -- "$parent_dir/release")"
requested_output="${1:-$release_base/$version-linux-$arch}"
release_root="$(realpath -m -- "$requested_output")"
if [[ "$(dirname -- "$release_root")" != "$release_base" || -z "$(basename -- "$release_root")" ]]; then
    echo "Refusing to clean unexpected release path: $release_root" >&2
    exit 1
fi

build_venv="${PACKIZARD_BUILD_VENV:-$project_dir/.venv-linux-$arch}"
if [[ ! -x "$build_venv/bin/python" ]]; then
    "$bootstrap_python" -m venv "$build_venv"
    "$build_venv/bin/python" -m pip install --upgrade pip
    "$build_venv/bin/python" -m pip install -r "$project_dir/requirements-build.txt"
fi
python="$build_venv/bin/python"

work="$release_root/work"
dist="$release_root/dist"
appdir="$release_root/Packizard_Builder.AppDir"
appimage="$release_root/Packizard-Builder-$version-Linux-$arch.AppImage"
archive="$release_root/Packizard-Builder-$version-Linux-$arch.tar.gz"

rm -rf -- "$release_root"
mkdir -p -- "$work" "$dist"
cd -- "$project_dir"

"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" Packizard_Builder.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" Packizard_Packer_Worker.spec
"$python" -m PyInstaller --noconfirm --clean --workpath "$work" --distpath "$dist" Packizard_Profile_Worker.spec

mkdir -p -- \
    "$dist/Packizard_Builder/workers/Packizard-Packer-Worker" \
    "$dist/Packizard_Builder/workers/Packizard-Profile-Worker"
cp -- "$dist/Packizard-Packer-Worker" "$dist/Packizard_Builder/workers/Packizard-Packer-Worker/Packizard-Packer-Worker"
cp -- "$dist/Packizard-Profile-Worker" "$dist/Packizard_Builder/workers/Packizard-Profile-Worker/Packizard-Profile-Worker"

"$python" scripts/prepare_pkg_bridge.py --rid "linux-$arch"
mkdir -p -- "$dist/Packizard_Builder/pkg_bridge"
cp -a -- "pkg_bridge/linux-$arch/." "$dist/Packizard_Builder/pkg_bridge/"
mkdir -p -- "$dist/Packizard_Builder/licenses/LibProsperoPKG"
cp -- "vendor/LibProsperoPKG/LICENSE" "$dist/Packizard_Builder/licenses/LibProsperoPKG/LICENSE"
chmod +x -- \
    "$dist/Packizard_Builder/Packizard_Builder" \
    "$dist/Packizard_Builder/workers/Packizard-Packer-Worker/Packizard-Packer-Worker" \
    "$dist/Packizard_Builder/workers/Packizard-Profile-Worker/Packizard-Profile-Worker" \
    "$dist/Packizard_Builder/pkg_bridge/Packizard.PkgBridge"

mkdir -p -- "$appdir/usr/bin" "$appdir/usr/lib" \
    "$appdir/usr/share/applications" \
    "$appdir/usr/share/icons/hicolor/256x256/apps" \
    "$appdir/usr/share/metainfo"
cp -a -- "$dist/Packizard_Builder/"* "$appdir/usr/bin/"

cat > "$appdir/AppRun" << 'RUNEOF'
#!/bin/bash
SELF="$(readlink -f "$0")"
HERE="$(dirname "$SELF")"
export PATH="$HERE/usr/bin:$PATH"
export LD_LIBRARY_PATH="$HERE/usr/lib:${LD_LIBRARY_PATH:-}"
if [ -z "${XDG_CONFIG_HOME:-}" ]; then export XDG_CONFIG_HOME="$HOME/.config"; fi
if [ -z "${XDG_DATA_HOME:-}" ]; then export XDG_DATA_HOME="$HOME/.local/share"; fi
exec "$HERE/usr/bin/Packizard_Builder" "$@"
RUNEOF
chmod +x -- "$appdir/AppRun"

cat > "$appdir/io.github.z3r3lkio.packizard-builder.desktop" << EOF_DESKTOP
[Desktop Entry]
Type=Application
Name=Packizard Builder
GenericName=Packizard Engine and PKG builder
Comment=Compress PS5 application data with Packizard Engine and build PKG files with integrated LibProsperoPKG
Exec=Packizard_Builder
Icon=packizard-builder
Categories=Utility;
Terminal=false
StartupNotify=true
X-AppImage-Version=$version
EOF_DESKTOP
cp -- "$appdir/io.github.z3r3lkio.packizard-builder.desktop" "$appdir/usr/share/applications/io.github.z3r3lkio.packizard-builder.desktop"
cp -- "$project_dir/resources/branding/packizard_icon.png" "$appdir/packizard-builder.png"
cp -- "$project_dir/resources/branding/packizard_icon.png" "$appdir/usr/share/icons/hicolor/256x256/apps/packizard-builder.png"

cat > "$appdir/usr/share/metainfo/packizard-builder.appdata.xml" << EOF_META
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>packizard-builder</id>
  <name>Packizard Builder</name>
  <summary>Integrated Packizard Engine compressor and LibProsperoPKG builder</summary>
  <description><p>Desktop interface for Packizard Engine compression workflows and integrated LibProsperoPKG package creation.</p></description>
  <launchable type="desktop-id">io.github.z3r3lkio.packizard-builder.desktop</launchable>
  <url type="homepage">https://github.com/z3r3lkio/packizard-builder</url>
  <releases><release version="$version" date="$(date +%Y-%m-%d)"/></releases>
  <content_rating type="oars-1.1"/>
</component>
EOF_META

# Always create a native portable archive. AppImage is an additional deliverable.
tar -C "$dist/Packizard_Builder" -czf "$archive" .

appimagetool="${APPIMAGETOOL:-$project_dir/tools/appimagetool-$appimage_arch.AppImage}"
appimage_url="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$appimage_arch.AppImage"
if [[ ! -x "$appimagetool" ]]; then
    mkdir -p -- "$(dirname -- "$appimagetool")"
    if command -v wget >/dev/null 2>&1; then
        wget -q "$appimage_url" -O "$appimagetool" || true
    elif command -v curl >/dev/null 2>&1; then
        curl -fsSL "$appimage_url" -o "$appimagetool" || true
    fi
    [[ -s "$appimagetool" ]] && chmod +x -- "$appimagetool"
fi
if [[ -x "$appimagetool" ]]; then
    rm -rf -- "$appdir/usr/share/metainfo"
    mkdir -p -- "$appdir/usr/share/metainfo"
    cat > "$appdir/usr/share/metainfo/io.github.z3r3lkio.packizard-builder.appdata.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>io.github.z3r3lkio.packizard-builder</id>
  <metadata_license>CC0-1.0</metadata_license>
  <project_license>GPL-3.0-or-later</project_license>
  <name>Packizard Builder</name>
  <summary>Integrated Packizard Engine compression and package workflow</summary>
  <description>
    <p>Packizard Builder provides an integrated desktop workflow for Packizard Engine compression and package creation.</p>
  </description>
  <developer id="io.github.z3r3lkio">
    <name>z3r3lkio</name>
  </developer>
  <launchable type="desktop-id">io.github.z3r3lkio.packizard-builder.desktop</launchable>
  <url type="homepage">https://github.com/z3r3lkio/packizard-builder</url>
  <releases>
    <release version="$version" date="$(date -u +%Y-%m-%d)"/>
  </releases>
  <content_rating type="oars-1.1"/>
</component>
EOF
    "$appimagetool" --appimage-extract-and-run "$appdir" "$appimage"
else
    echo "appimagetool unavailable for $appimage_arch; portable tar.gz is still valid" >&2
fi

(
    cd -- "$release_root"
    : > "SHA256SUMS-Linux-$arch.txt"
    sha256sum "$(basename -- "$archive")" >> "SHA256SUMS-Linux-$arch.txt"
    if [[ -f "$appimage" ]]; then sha256sum "$(basename -- "$appimage")" >> "SHA256SUMS-Linux-$arch.txt"; fi
)
echo "Built $archive"
[[ -f "$appimage" ]] && echo "Built $appimage"
cat -- "$release_root/SHA256SUMS-Linux-$arch.txt"
