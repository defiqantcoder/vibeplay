#!/usr/bin/env bash
# Build Flatpak bundle for VibePlay
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

MANIFEST_PATH="packaging/flatpak/org.vibeplay.VibePlay.yml"
BUILD_DIR="${REPO_DIR}/build/flatpak-build"
REPO_DIR_FLATPAK="${REPO_DIR}/build/flatpak-repo"
BUNDLE_OUTPUT="${REPO_DIR}/dist/vibeplay.flatpak"

cd "${REPO_DIR}"

if ! command -v flatpak-builder >/dev/null 2>&1; then
    echo "Error: flatpak-builder is not installed."
    echo "Please install it: sudo apt install flatpak-builder"
    # Using return to avoid exiting the subshell during tests if sourced
    return 1 2>/dev/null
fi

echo "=========================================================="
echo " Building Flatpak for VibePlay"
echo "=========================================================="

mkdir -p "${REPO_DIR}/dist"

flatpak-builder --force-clean --repo="${REPO_DIR_FLATPAK}" "${BUILD_DIR}" "${MANIFEST_PATH}"

echo "Creating Flatpak bundle..."
flatpak build-bundle "${REPO_DIR_FLATPAK}" "${BUNDLE_OUTPUT}" org.vibeplay.VibePlay

echo "=========================================================="
echo " Flatpak bundle successfully created:"
echo " ${BUNDLE_OUTPUT}"
echo "=========================================================="
