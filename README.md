# PIC16F877A Assembly — VS Code Development, Simulation, Debugging & USB Flashing Environment (Linux)

A complete Linux development environment for developing, compiling, simulating, debugging, and flashing **PIC16F877A** Assembly code inside **Visual Studio Code**.

---

## Features

- **Top Run Button (Code Runner):** Open any `.asm` file and click the **Run Code (Play)** button at the top-right of the editor window to build and open the simulation in PICSimLab.
- **Active-File Aware Workflow:** Whichever `.asm` file is currently open (`exp1.asm`, `exp2.asm`, `main.asm`, `test.asm`, etc.) is automatically targeted by all build, simulation, debug, and flash actions.
- **Action Menu (F4):** Press **F4** or click **PIC Menu (F4)** in the bottom status bar to view all operations and their shortcuts in an interactive dropdown.
- **In-Editor Step-by-Step Debugger (F8):**
  - Powered by a custom Debug Adapter Protocol (DAP) server (`.vscode/pic16_debug_adapter.py`) bridging `gpasm` (`.lst`/`.cod`) and `gpsim`.
  - Supports Breakpoints, Step Over (F10), Step Into (F11), Continue (F5), and Stop (Shift+F5).
  - Inspects Core Registers (W, STATUS with RP1:RP0, Z, C, DC), User Variables (EQU / CBLOCK), Ports & TRIS (PORTA-PORTE with pin indicators), SFRs, and RAM memory.
  - Concise value formatting: `0xHH | 0dNUM | 0bNNNNNNNN` with change indicators (`*`).
- **Live Terminal Table Debugger (Ctrl+F8):**
  - Terminal-based dashboard (`.vscode/pic16_terminal_debugger.py`) showing source code, registers, variables, and port states side-by-side.
- **PICkit 2 USB Hardware Flashing (F9 / Shift+F9):**
  - Direct USB flashing to physical PIC16F877A hardware using `pk2cmd -P PIC16F877A -M -F <active_file>.hex -R`.

---

## Quick Start (Automated Setup)

Clone the repository and run `setup.sh`:

```bash
git clone https://github.com/Nylord5578ygt/pic16f877a-vscode-linux.git
cd pic16f877a-vscode-linux
chmod +x setup.sh
./setup.sh
```

### What `setup.sh` Configures:
1. Installs system packages: `gputils` (`gpasm`), `gpsim`, `python3`, `curl`, `fuse2`.
2. Installs Visual Studio Code (`visual-studio-code-bin` via `yay` on Arch, or official packages on Debian/Fedora) if missing.
3. Downloads the official PICSimLab AppImage to `~/.local/bin/picsimlab` and symlinks it to `/usr/bin/picsimlab`.
4. Installs `pk2cmd` (`pk2cmd-plus`) using the Web Archive `PK2DeviceFile_v1.63.148.zip` mirror and adds `/etc/udev/rules.d/99-pickit2.rules` for passwordless USB flashing.
5. Installs required VS Code extensions:
   - `formulahendry.code-runner` (Top Run Code button)
   - `maziac.asm-code-lens` (Assembly syntax and symbols)
   - `duckymomo20012.status-bar-btn` (Bottom status bar action buttons)
   - `microchip.mplab-core-da` (In-editor debugger DAP client)
6. Configures Code Runner executor maps, status bar buttons, and F-key shortcuts.

---

## Editor Controls & Shortcuts

### Top Editor Title Button (Code Runner)
- **Run Code (Play button at top-right of editor tab):** Compiles active `.asm` with `gpasm` and launches `PICSimLab`.
- **Keyboard shortcut:** `Ctrl+Alt+N`
- **Custom command (Build & Flash USB):** `Ctrl+Alt+K`

### Status Bar Buttons & Keyboard Shortcuts

| Button | Shortcut | Action |
| :--- | :---: | :--- |
| **PIC Menu (F4)** | F4 | Opens the interactive task selection menu |
| **Build & Sim (F5)** | F5 | Compiles `.asm` and launches PICSimLab |
| **Build (F6)** | F6 | `gpasm -p 16f877a <active_file>.asm` (generates `.hex`, `.cod`, `.lst`) |
| **Simulate (F7)** | F7 | `picsimlab "PICGenios" "PIC16F877A" <active_file>.hex` |
| **Debug (F8)** | F8 | Starts in-editor step-by-step debugger |
| **Flash USB (F9)** | F9 | `pk2cmd -P PIC16F877A -M -F <active_file>.hex -R` |
| *(In PIC Menu)* | Shift+F9 | Compiles `.asm` then flashes `.hex` via USB |
| *(In PIC Menu)* | Ctrl+F8 | Launches live terminal table debugger |

---

## Step-by-Step Debugger (F8)

1. Open any `.asm` file and press **F8** (or click **Debug (F8)** in the status bar).
2. The current instruction line is highlighted in yellow:
   - **F10 (Step Over):** Steps to the next line (`call` subroutines execute in a single step).
   - **F11 (Step Into):** Enters subroutines (`call`).
   - **F5 (Continue):** Runs until the next Breakpoint.
   - **Shift+F5 (Stop):** Exits the debugger.
3. In the left **VARIABLES** panel, inspect values in `0xHH | 0dNUM | 0bNNNNNNNN` format:
   - **1. Core Registers:** W, STATUS (RP1:RP0, Z, C, DC), PC, Cycles, FSR, INDF.
   - **2. User Variables:** Variables defined with `EQU` or `CBLOCK`.
   - **3. Ports & TRIS:** PORTA-PORTE and TRISA-TRISE.
   - **4. Special Function Registers (SFR):** Timers, interrupts, ADC, etc.
   - **5. RAM Memory:** Non-zero memory and Bank 0-3 views.

---

## Manual Installation Notes (Arch Linux Reference)

### 1. Visual Studio Code
```bash
yay -S visual-studio-code-bin
```

### 2. PICSimLab AppImage & /usr/bin/picsimlab Symlink
```bash
mkdir -p ~/.local/bin
curl -L "https://github.com/lcgamboa/picsimlab/releases/download/v0.9.3/PICSimLab-0.9.3_260920_Ubuntu_22.04.5_LTS_x86_64.AppImage" -o ~/.local/bin/picsimlab
chmod +x ~/.local/bin/picsimlab
sudo ln -sf ~/.local/bin/picsimlab /usr/bin/picsimlab
```

### 3. pk2cmd-plus (PK2DeviceFile_v1.63.148.zip Download Fix)
```bash
git clone https://aur.archlinux.org/pk2cmd-plus.git ~/.cache/yay/pk2cmd-plus
cd ~/.cache/yay/pk2cmd-plus
curl -L -A "Mozilla/5.0" -o PK2DeviceFile_v1.63.148.zip "https://web.archive.org/web/20210226162319if_/http://www.microchip.com/forums/download.axd?file=0;749972"
makepkg -si
```

---

## Project Structure

```text
├── .vscode/
│   ├── launch.json                # VS Code Debugger (DAP) configuration
│   ├── tasks.json                 # Build, PICSimLab, pk2cmd USB Flash & Debug tasks
│   ├── settings.json              # Code Runner & Status Bar button configuration
│   ├── keybindings.json           # F4..F9 shortcut definitions (installed by setup.sh)
│   ├── pic16_debug_adapter.py     # In-Editor DAP Server (gpasm + gpsim bridge)
│   └── pic16_terminal_debugger.py # Interactive Terminal Table Debugger
├── setup.sh                       # Automated cross-distro Linux installer script
├── main.asm                       # Sample PIC16F877A Assembly program
├── exp1.asm / exp2.asm            # Example PIC16F877A Assembly exercises
└── README.md                      # Project documentation
```
