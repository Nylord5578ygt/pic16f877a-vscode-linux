#!/usr/bin/env bash
# ==============================================================================
# PIC16F877A Assembly (VS Code) - Automated Linux Setup Script
# Supports: Arch/Manjaro, Ubuntu/Debian/Mint, Fedora, and other Linux distros
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
RESET='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${CYAN}${BOLD}======================================================================${RESET}"
echo -e "${CYAN}${BOLD}   PIC16F877A Assembly & VS Code Development Environment Installer    ${RESET}"
echo -e "${CYAN}${BOLD}======================================================================${RESET}"
echo ""

# ------------------------------------------------------------------------------
# 1. Detect Linux Distro & Install Core Packages (gpasm, gpsim, python3, curl)
# ------------------------------------------------------------------------------
echo -e "${BOLD}[1/6] Checking system packages (gputils/gpasm, gpsim, python3, fuse2)...${RESET}"

if command -v pacman >/dev/null 2>&1; then
    DISTRO="arch"
    echo -e "  -> Detected Distro: ${GREEN}Arch Linux / Manjaro (pacman)${RESET}"
    sudo pacman -S --needed --noconfirm python gputils gpsim base-devel git libusb curl unzip fuse2

    # Ensure yay is installed for AUR packages
    if ! command -v yay >/dev/null 2>&1; then
        echo -e "  -> Installing ${CYAN}yay${RESET} AUR helper..."
        TMP_YAY="$(mktemp -d)"
        git clone https://aur.archlinux.org/yay-bin.git "$TMP_YAY/yay-bin"
        (cd "$TMP_YAY/yay-bin" && makepkg -si --noconfirm)
        rm -rf "$TMP_YAY"
    fi

elif command -v apt >/dev/null 2>&1; then
    DISTRO="debian"
    echo -e "  -> Detected Distro: ${GREEN}Ubuntu / Debian / Mint (apt)${RESET}"
    sudo apt update
    sudo apt install -y python3 gputils gpsim build-essential git libusb-dev curl wget unzip libfuse2t64 || \
    sudo apt install -y python3 gputils gpsim build-essential git libusb-dev curl wget unzip libfuse2

elif command -v dnf >/dev/null 2>&1; then
    DISTRO="fedora"
    echo -e "  -> Detected Distro: ${GREEN}Fedora / RHEL (dnf)${RESET}"
    sudo dnf install -y python3 gputils gpsim gcc gcc-c++ make git libusb-compat-0.1-devel curl wget unzip fuse-libs
else
    DISTRO="other"
    echo -e "${YELLOW}  [!] Package manager not recognized. Please ensure python3, gputils, gpsim, and curl are installed.${RESET}"
fi

# ------------------------------------------------------------------------------
# 2. Install VS Code (visual-studio-code-bin) if not already installed
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[2/6] Checking Visual Studio Code installation...${RESET}"

VSCODE_BIN=""
for candidate in code code-oss codium vscodium; do
    if command -v "$candidate" >/dev/null 2>&1; then
        VSCODE_BIN="$candidate"
        break
    fi
done

if [ -z "$VSCODE_BIN" ]; then
    echo -e "  -> VS Code not found. Installing ${CYAN}visual-studio-code-bin${RESET}..."
    if [ "$DISTRO" = "arch" ]; then
        yay -S --needed --noconfirm visual-studio-code-bin
        VSCODE_BIN="code"
    elif [ "$DISTRO" = "debian" ]; then
        TMP_DEB="$(mktemp -d)"
        curl -L "https://code.visualstudio.com/sha/download?build=stable&os=linux-deb-x64" -o "$TMP_DEB/vscode.deb"
        sudo apt install -y "$TMP_DEB/vscode.deb"
        rm -rf "$TMP_DEB"
        VSCODE_BIN="code"
    elif [ "$DISTRO" = "fedora" ]; then
        sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
        sudo sh -c 'echo -e "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" > /etc/yum.repos.d/vscode.repo'
        sudo dnf install -y code
        VSCODE_BIN="code"
    fi
else
    echo -e "  -> Found VS Code CLI: ${GREEN}$VSCODE_BIN${RESET}"
fi

# ------------------------------------------------------------------------------
# 3. Install PICSimLab (AppImage from GitHub + Symlink to /usr/bin/picsimlab)
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[3/6] Checking PICSimLab simulator (AppImage + /usr/bin/picsimlab symlink)...${RESET}"

mkdir -p "$HOME/.local/bin"

if ! command -v picsimlab >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/picsimlab" ]; then
    echo -e "  -> Downloading ${CYAN}PICSimLab v0.9.3 AppImage${RESET}..."
    APPIMAGE_URL="https://github.com/lcgamboa/picsimlab/releases/download/v0.9.3/PICSimLab-0.9.3_260920_Ubuntu_22.04.5_LTS_x86_64.AppImage"

    curl -L "$APPIMAGE_URL" -o "$HOME/.local/bin/picsimlab"
    chmod +x "$HOME/.local/bin/picsimlab"
    echo -e "  -> Downloaded PICSimLab AppImage to ${GREEN}$HOME/.local/bin/picsimlab${RESET}"
fi

# Always ensure /usr/bin/picsimlab is linked if AppImage is in ~/.local/bin/picsimlab
if [ -x "$HOME/.local/bin/picsimlab" ] && [ ! -e "/usr/bin/picsimlab" ]; then
    echo -e "  -> Linking ${CYAN}$HOME/.local/bin/picsimlab${RESET} -> ${GREEN}/usr/bin/picsimlab${RESET}..."
    sudo ln -sf "$HOME/.local/bin/picsimlab" /usr/bin/picsimlab
fi

# ------------------------------------------------------------------------------
# 4. Install pk2cmd (PICkit 2 USB Programmer + PK2DeviceFile workaround)
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[4/6] Checking pk2cmd (PICkit 2 USB Flasher)...${RESET}"

PK2_ARCHIVE_URL="https://web.archive.org/web/20210226162319if_/http://www.microchip.com/forums/download.axd?file=0;749972"

if ! command -v pk2cmd >/dev/null 2>&1; then
    if [ "$DISTRO" = "arch" ]; then
        echo -e "  -> Building ${CYAN}pk2cmd-plus${RESET} with archived PK2DeviceFile_v1.63.148.zip..."
        mkdir -p "$HOME/.cache/yay"
        rm -rf "$HOME/.cache/yay/pk2cmd-plus"
        git clone https://aur.archlinux.org/pk2cmd-plus.git "$HOME/.cache/yay/pk2cmd-plus"
        (
            cd "$HOME/.cache/yay/pk2cmd-plus"
            curl -L -A "Mozilla/5.0" -o PK2DeviceFile_v1.63.148.zip "$PK2_ARCHIVE_URL"
            makepkg -si --noconfirm
        )
    else
        echo -e "  -> Building ${CYAN}pk2cmd${RESET} from source and installing PK2DeviceFile.dat..."
        TMP_PK2="$(mktemp -d)"
        if git clone --depth 1 https://github.com/jaka/pk2cmd.git "$TMP_PK2/pk2cmd"; then
            make -C "$TMP_PK2/pk2cmd/pk2cmd" linux
            sudo make -C "$TMP_PK2/pk2cmd/pk2cmd" install
            curl -L -A "Mozilla/5.0" -o "$TMP_PK2/PK2DeviceFile_v1.63.148.zip" "$PK2_ARCHIVE_URL" || true
            if [ -f "$TMP_PK2/PK2DeviceFile_v1.63.148.zip" ]; then
                unzip -o "$TMP_PK2/PK2DeviceFile_v1.63.148.zip" -d "$TMP_PK2" || true
                DAT_FILE="$(find "$TMP_PK2" -iname "PK2DeviceFile.dat" | head -n 1 || true)"
                if [ -n "$DAT_FILE" ]; then
                    sudo mkdir -p /usr/share/pk2
                    sudo cp -f "$DAT_FILE" /usr/share/pk2/PK2DeviceFile.dat
                    sudo cp -f "$DAT_FILE" /usr/local/bin/PK2DeviceFile.dat
                fi
            fi
        fi
        rm -rf "$TMP_PK2"
    fi
else
    echo -e "  -> ${GREEN}pk2cmd${RESET} is already installed."
fi

# Configure PICkit 2 USB udev rules (allows flashing without sudo)
UDEV_FILE="/etc/udev/rules.d/99-pickit2.rules"
if [ ! -f "$UDEV_FILE" ]; then
    echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="04d8", ATTRS{idProduct}=="0033", MODE="0666", GROUP="plugdev", TAG+="uaccess"' | sudo tee "$UDEV_FILE" >/dev/null
    sudo udevadm control --reload-rules 2>/dev/null || true
    sudo udevadm trigger 2>/dev/null || true
    echo -e "  -> Added PICkit 2 USB udev rules ($UDEV_FILE)."
fi

# ------------------------------------------------------------------------------
# 5. Install VS Code Extensions & Configure Shortcuts / Status Bar Buttons
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[5/6] Installing VS Code extensions and configuring shortcuts (F4..F9)...${RESET}"

for candidate in code code-oss codium vscodium; do
    if command -v "$candidate" >/dev/null 2>&1; then
        VSCODE_BIN="$candidate"
        break
    fi
done

if [ -n "$VSCODE_BIN" ]; then
    "$VSCODE_BIN" --install-extension formulahendry.code-runner --force || true
    "$VSCODE_BIN" --install-extension maziac.asm-code-lens --force || true
    "$VSCODE_BIN" --install-extension duckymomo20012.status-bar-btn --force || true
    "$VSCODE_BIN" --install-extension microchip.mplab-core-da --force || true
else
    echo -e "${RED}  [!] Could not find VS Code binary to install extensions.${RESET}"
fi

# Enable .asm breakpoints in MPLAB Debug Adapter extension
python3 - <<'PYEOF'
import glob, json, os

patterns = [
    os.path.expanduser("~/.vscode*/extensions/microchip.mplab-core-da-*/package.json"),
    os.path.expanduser("~/.var/app/com.visualstudio.code*/data/vscode/extensions/microchip.mplab-core-da-*/package.json"),
]
for pat in patterns:
    for pkg_path in glob.glob(pat):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            bps = data.setdefault("contributes", {}).setdefault("breakpoints", [])
            existing = {b.get("language") for b in bps if isinstance(b, dict)}
            changed = False
            for lang in ("asm-collection", "asm"):
                if lang not in existing:
                    bps.append({"language": lang})
                    changed = True
            if changed:
                with open(pkg_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent="\t")
                print(f"  -> Enabled .asm breakpoints in: {pkg_path}")
        except Exception:
            pass
PYEOF

chmod +x "$PROJECT_DIR/.vscode/pic16_debug_adapter.py" "$PROJECT_DIR/.vscode/pic16_terminal_debugger.py"

python3 - "$PROJECT_DIR" <<'PYEOF'
import json, os, shutil, sys

project_dir = sys.argv[1]
vscode_kb_src = os.path.join(project_dir, ".vscode", "keybindings.json")
vscode_settings_src = os.path.join(project_dir, ".vscode", "settings.json")

config_dirs = [
    os.path.expanduser("~/.config/Code/User"),
    os.path.expanduser("~/.config/Code - OSS/User"),
    os.path.expanduser("~/.config/VSCodium/User"),
]

existing_dirs = [d for d in config_dirs if os.path.isdir(os.path.dirname(d))]
if not existing_dirs:
    existing_dirs = [
        os.path.expanduser("~/.config/Code/User"),
        os.path.expanduser("~/.config/Code - OSS/User"),
    ]

with open(vscode_kb_src, "r", encoding="utf-8") as f:
    new_kbs = json.load(f)

with open(vscode_settings_src, "r", encoding="utf-8") as f:
    ws_settings = json.load(f)

for udir in existing_dirs:
    os.makedirs(udir, exist_ok=True)

    # 1. Merge keybindings.json
    kb_target = os.path.join(udir, "keybindings.json")
    current_kbs = []
    if os.path.exists(kb_target):
        shutil.copy2(kb_target, kb_target + ".bak")
        try:
            with open(kb_target, "r", encoding="utf-8") as f:
                current_kbs = json.load(f)
            if not isinstance(current_kbs, list):
                current_kbs = []
        except Exception:
            current_kbs = []

    new_keys = {item.get("key") for item in new_kbs}
    merged_kbs = [item for item in current_kbs if item.get("key") not in new_keys] + new_kbs
    with open(kb_target, "w", encoding="utf-8") as f:
        json.dump(merged_kbs, f, indent=4, ensure_ascii=False)

    # 2. Merge settings.json
    st_target = os.path.join(udir, "settings.json")
    current_st = {}
    if os.path.exists(st_target):
        shutil.copy2(st_target, st_target + ".bak")
        try:
            with open(st_target, "r", encoding="utf-8") as f:
                current_st = json.load(f)
            if not isinstance(current_st, dict):
                current_st = {}
        except Exception:
            current_st = {}

    for k, v in ws_settings.items():
        current_st[k] = v

    with open(st_target, "w", encoding="utf-8") as f:
        json.dump(current_st, f, indent=4, ensure_ascii=False)

    print(f"  -> Configured VS Code user profile: {udir}")
PYEOF

# ------------------------------------------------------------------------------
# 6. Final Verification Summary
# ------------------------------------------------------------------------------
echo ""
echo -e "${BOLD}[6/6] Installation verification:${RESET}"
for tool in gpasm gpsim picsimlab pk2cmd python3 "${VSCODE_BIN:-code}"; do
    if command -v "$tool" >/dev/null 2>&1 || [ -x "/usr/bin/$tool" ] || [ -x "$HOME/.local/bin/$tool" ]; then
        echo -e "  [OK] ${GREEN}$tool${RESET} is ready"
    else
        echo -e "  [!] ${YELLOW}$tool${RESET} not found in PATH"
    fi
done

echo ""
echo -e "${GREEN}${BOLD}======================================================================${RESET}"
echo -e "${GREEN}${BOLD} [OK] Setup complete! Open this folder in VS Code to start developing:${RESET}"
echo -e "    ${CYAN}${VSCODE_BIN:-code} \"$PROJECT_DIR\"${RESET}"
echo -e "${GREEN}${BOLD}======================================================================${RESET}"
