#!/usr/bin/env bash

set -euo pipefail

PREFIX="${HOME}/.local"
DRY_RUN=0
ENABLE_SYSTEMD=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --enable-systemd)
            ENABLE_SYSTEMD=1
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

if [[ $DRY_RUN -eq 1 ]]; then
    echo "[Dry Run] Would install to prefix: ${PREFIX}"
    echo "[Dry Run] Would enable systemd: ${ENABLE_SYSTEMD}"
    exit 0
fi

echo "Installing VibePlay Desktop..."

BIN_DIR="${PREFIX}/bin"
ICON_DIR="${PREFIX}/share/icons/hicolor/scalable/apps"
APP_DIR="${PREFIX}/share/applications"
SYSTEMD_DIR="${HOME}/.config/systemd/user"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

mkdir -p "${BIN_DIR}" "${ICON_DIR}" "${APP_DIR}"

if [[ -f "dist/vibeplay-desktop" ]]; then
    echo "Installing binary to ${BIN_DIR}/vibeplay-desktop"
    cp "dist/vibeplay-desktop" "${BIN_DIR}/vibeplay-desktop"
    chmod +x "${BIN_DIR}/vibeplay-desktop"
else
    echo "dist/vibeplay-desktop not found. Creating a wrapper script..."
    cat << WRAPPER > "${BIN_DIR}/vibeplay-desktop"
#!/usr/bin/env bash
if command -v uv >/dev/null 2>&1 && [[ -d "${REPO_DIR}" ]]; then
    exec uv run --project "${REPO_DIR}" python -m vibeplay.desktop "\$@"
else
    exec python3 -m vibeplay.desktop "\$@"
fi
WRAPPER
    chmod +x "${BIN_DIR}/vibeplay-desktop"
fi

if [[ -f "dist/vibeplay" ]]; then
    echo "Installing cli binary to ${BIN_DIR}/vibeplay"
    cp "dist/vibeplay" "${BIN_DIR}/vibeplay"
    chmod +x "${BIN_DIR}/vibeplay"
else
    echo "dist/vibeplay not found. Creating a wrapper script..."
    cat << WRAPPER > "${BIN_DIR}/vibeplay"
#!/usr/bin/env bash
if command -v uv >/dev/null 2>&1 && [[ -d "${REPO_DIR}" ]]; then
    exec uv run --project "${REPO_DIR}" python -m vibeplay.cli "\$@"
else
    exec python3 -m vibeplay.cli "\$@"
fi
WRAPPER
    chmod +x "${BIN_DIR}/vibeplay"
fi

echo "Installing icon..."
cp "packaging/icons/vibeplay.svg" "${ICON_DIR}/vibeplay.svg"

echo "Installing .desktop file..."
sed "s|Exec=vibeplay-desktop|Exec=${BIN_DIR}/vibeplay-desktop|g" "packaging/vibeplay.desktop" | sed "s|Exec=vibeplay |Exec=${BIN_DIR}/vibeplay |g" > "${APP_DIR}/vibeplay.desktop"

if [[ $ENABLE_SYSTEMD -eq 1 ]]; then
    echo "Installing systemd service..."
    mkdir -p "${SYSTEMD_DIR}"
    sed "s|ExecStart=/usr/bin/env vibeplay|ExecStart=${BIN_DIR}/vibeplay|g" "packaging/vibeplay.service" > "${SYSTEMD_DIR}/vibeplay.service"
    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload || true
        echo "systemctl --user daemon-reload executed."
    fi
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    echo "Updating desktop database..."
    update-desktop-database "${APP_DIR}" || true
fi

if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    echo "Updating icon cache..."
    gtk-update-icon-cache -f -t "${PREFIX}/share/icons/hicolor" || true
fi

echo "Installation complete!"
