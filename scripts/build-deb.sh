#!/usr/bin/env bash
# Build Debian/Ubuntu .deb package for vibeplay
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERSION="0.2.0"
ARCH="amd64"
PKG_NAME="vibeplay"
DEB_NAME="${PKG_NAME}_${VERSION}_${ARCH}.deb"
OUTPUT_DIR="${REPO_DIR}/dist"
STAGE_DIR="${REPO_DIR}/build/deb/${PKG_NAME}_${VERSION}_${ARCH}"

SKIP_PYINSTALLER=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-pyinstaller)
            SKIP_PYINSTALLER=1
            shift
            ;;
        --version)
            VERSION="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=========================================================="
echo " Building Debian package: ${DEB_NAME}"
echo "=========================================================="

cd "${REPO_DIR}"

if [[ ${SKIP_PYINSTALLER} -eq 0 && ! -f "dist/vibeplay-desktop" ]]; then
    echo "dist/vibeplay-desktop not found. Running PyInstaller build..."
    if command -v uv >/dev/null 2>&1; then
        uv run pyinstaller packaging/vibeplay.spec
    elif command -v pyinstaller >/dev/null 2>&1; then
        pyinstaller packaging/vibeplay.spec
    else
        echo "Error: Neither uv nor pyinstaller found to build executable."
        exit 1
    fi
fi

# Clean and create staging directory structure
rm -rf "${STAGE_DIR}"
mkdir -p "${STAGE_DIR}/DEBIAN"
mkdir -p "${STAGE_DIR}/usr/bin"
mkdir -p "${STAGE_DIR}/usr/share/applications"
mkdir -p "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps"
mkdir -p "${STAGE_DIR}/usr/lib/systemd/user"
mkdir -p "${STAGE_DIR}/usr/share/doc/${PKG_NAME}"
mkdir -p "${OUTPUT_DIR}"

# 1. Install executable binaries
if [[ -f "dist/vibeplay-desktop" ]]; then
    echo "Installing binary dist/vibeplay-desktop..."
    cp "dist/vibeplay-desktop" "${STAGE_DIR}/usr/bin/vibeplay-desktop"
    chmod 0755 "${STAGE_DIR}/usr/bin/vibeplay-desktop"
    # Symlink vibeplay -> vibeplay-desktop so CLI and GUI share the self-contained runtime
    ln -sf "vibeplay-desktop" "${STAGE_DIR}/usr/bin/vibeplay"
else
    echo "Warning: dist/vibeplay-desktop not found; creating stub wrappers for testing..."
    cat << 'WRAPPER' > "${STAGE_DIR}/usr/bin/vibeplay-desktop"
#!/usr/bin/env bash
exec python3 -m vibeplay.desktop "$@"
WRAPPER
    chmod 0755 "${STAGE_DIR}/usr/bin/vibeplay-desktop"

    cat << 'WRAPPER' > "${STAGE_DIR}/usr/bin/vibeplay"
#!/usr/bin/env bash
exec python3 -m vibeplay.cli "$@"
WRAPPER
    chmod 0755 "${STAGE_DIR}/usr/bin/vibeplay"
fi

# 2. Install FreeDesktop assets
cp "packaging/vibeplay.desktop" "${STAGE_DIR}/usr/share/applications/vibeplay.desktop"
chmod 0644 "${STAGE_DIR}/usr/share/applications/vibeplay.desktop"

cp "packaging/icons/vibeplay.svg" "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps/vibeplay.svg"
chmod 0644 "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps/vibeplay.svg"

# 3. Install user systemd service
cp "packaging/vibeplay.service" "${STAGE_DIR}/usr/lib/systemd/user/vibeplay.service"
chmod 0644 "${STAGE_DIR}/usr/lib/systemd/user/vibeplay.service"

# 4. Install documentation & copyright
if [[ -f "packaging/debian/copyright" ]]; then
    cp "packaging/debian/copyright" "${STAGE_DIR}/usr/share/doc/${PKG_NAME}/copyright"
    chmod 0644 "${STAGE_DIR}/usr/share/doc/${PKG_NAME}/copyright"
fi

# 5. Configure control files
if [[ -f "packaging/debian/control" ]]; then
    cp "packaging/debian/control" "${STAGE_DIR}/DEBIAN/control"
    chmod 0644 "${STAGE_DIR}/DEBIAN/control"
else
    cat << CONTROL > "${STAGE_DIR}/DEBIAN/control"
Package: ${PKG_NAME}
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: ${ARCH}
Maintainer: VibePlay Contributors <dev@vibeplay.org>
Depends: libc6, libwebkit2gtk-4.1-0, mpd, libasound2, libnotify-bin
Description: Precision Audiophile Music Console & Essentia Vibe Engine
 VibePlay is a bit-perfect ALSA/MPD audio console featuring an Essentia-powered
 vibe clustering engine, SOFA 7.1.4 HRTF spatial convolution, parametric EQ,
 and a hardware telemetry HUD.
CONTROL
    chmod 0644 "${STAGE_DIR}/DEBIAN/control"
fi

if [[ -f "packaging/debian/postinst" ]]; then
    cp "packaging/debian/postinst" "${STAGE_DIR}/DEBIAN/postinst"
    chmod 0755 "${STAGE_DIR}/DEBIAN/postinst"
fi

if [[ -f "packaging/debian/postrm" ]]; then
    cp "packaging/debian/postrm" "${STAGE_DIR}/DEBIAN/postrm"
    chmod 0755 "${STAGE_DIR}/DEBIAN/postrm"
fi

# 6. Build the .deb archive using dpkg-deb
echo "Packaging into ${OUTPUT_DIR}/${DEB_NAME}..."
dpkg-deb --build --root-owner-group "${STAGE_DIR}" "${OUTPUT_DIR}/${DEB_NAME}"

echo "=========================================================="
echo " Debian package successfully created:"
echo " ${OUTPUT_DIR}/${DEB_NAME}"
echo ""
echo " To install on Ubuntu/Debian:"
echo "   sudo apt install ./${OUTPUT_DIR}/${DEB_NAME}"
echo "   # or"
echo "   sudo dpkg -i ${OUTPUT_DIR}/${DEB_NAME}"
echo "=========================================================="
