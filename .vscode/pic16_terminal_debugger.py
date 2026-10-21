#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PIC16F877A Live Table Debugger (Terminal UI)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pic16_debug_adapter import GpsimController, fmt_pins

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BLUE = "\033[94m"
BG_HILITE = "\033[48;5;236m"


def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def format_cell_row(name, val, pval, info=""):
    if val is None:
        val = 0
    if pval is None:
        pval = val
    changed = (val & 0xFF) != (pval & 0xFF)
    v = val & 0xFF
    val_str = f"0x{v:02X} | 0d{v:<3d} | 0b{v:08b}"

    if changed:
        mark = f"{YELLOW}{BOLD}*{RESET}"
        color = f"{YELLOW}{BOLD}"
    else:
        mark = " "
        color = ""
    end_c = RESET if color else ""
    return f"  {mark} {color}{name:<11}{end_c} : {color}{val_str}{end_c}  {info}"


def render_dashboard(sim, src_lines, bp_lines, last_msg=""):
    clear_screen()
    st = sim.curr_state
    prev = sim.prev_state or st
    ram = st["ram"]
    pram = prev["ram"]
    pc = st["pc"]
    curr_line = sim.pc_to_line.get(pc, 1)
    status = st["status"]
    bank = (status >> 5) & 3
    z = (status >> 2) & 1
    dc = (status >> 1) & 1
    c = status & 1

    print(
        f"{BOLD}{CYAN}╔══════════════════════════════════════════════════════════════════════════════════╗{RESET}"
    )
    print(
        f"{BOLD}{CYAN}║ PIC16F877A DEBUGGER{RESET} │ {BOLD}{os.path.basename(sim.asm_path):<14}{RESET} "
        f"│ Step: {BOLD}{sim.step_count:<4d}{RESET} │ PC: {BOLD}0x{pc:04X}{RESET} │ Cycles: {BOLD}{st['cycles']:<6d}{RESET} {BOLD}{CYAN}║{RESET}"
    )
    print(
        f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════════════════════════════╝{RESET}"
    )

    # 1. SOURCE CODE
    print(f"\n{BOLD}{BLUE}[1] SOURCE CODE [Line {curr_line}]:{RESET}")
    total_lines = len(src_lines)
    start_l = max(1, curr_line - 4)
    end_l = min(total_lines, start_l + 9)
    if end_l - start_l < 9:
        start_l = max(1, end_l - 9)

    for lno in range(start_l, end_l + 1):
        code_txt = src_lines[lno - 1].rstrip("\r\n")
        pcs = sim.line_to_pcs.get(lno, [])
        pc_str = f"0x{pcs[0]:04X}" if pcs else "      "
        bp_mark = f"{RED}B{RESET}" if lno in bp_lines else " "
        if lno == curr_line:
            print(f"{BG_HILITE} {bp_mark}{GREEN}{BOLD}==> {lno:3d} [{pc_str}] │ {code_txt:<62}{RESET}")
        else:
            print(f" {bp_mark}    {DIM}{lno:3d} [{pc_str}]{RESET} │ {code_txt}")

    # 2. CORE REGISTERS
    print(f"\n{BOLD}{MAGENTA}[2] CORE REGISTERS:{RESET}")
    print(format_cell_row("W", st["w"], prev["w"]))
    print(format_cell_row("STATUS", status, prev["status"], f"[0x03 | Bank {bank} | Z={z} DC={dc} C={c}]"))
    print(format_cell_row("PCL", ram[0x02], pram[0x02], f"[0x02 | PC=0x{pc:04X}]"))
    if (ram[0x04] or 0) != 0:
        print(format_cell_row("FSR", ram[0x04], pram[0x04], f"[0x04 | INDF=0x{(ram[ram[0x04]] or 0):02X}]"))

    # 3. USER VARIABLES
    print(f"\n{BOLD}{GREEN}[3] USER VARIABLES:{RESET}")
    if not sim.user_vars:
        print(f"  {DIM}[No user variables defined]{RESET}")
    else:
        for vname, vaddr, _ in sim.user_vars:
            vbank = vaddr >> 7
            print(format_cell_row(vname, ram[vaddr], pram[vaddr], f"[0x{vaddr:02X} | Bank {vbank}]"))

    # 4. PORTS & TRIS
    print(f"\n{BOLD}{CYAN}[4] PORTS & TRIS:{RESET}")
    for pname, paddr, tname, taddr in [
        ("PORTA", 0x05, "TRISA", 0x85),
        ("PORTB", 0x06, "TRISB", 0x86),
        ("PORTC", 0x07, "TRISC", 0x87),
        ("PORTD", 0x08, "TRISD", 0x88),
        ("PORTE", 0x09, "TRISE", 0x89),
    ]:
        pv = ram[paddr] or 0
        ppv = pram[paddr] or 0
        tv = ram[taddr] if ram[taddr] is not None else 0xFF
        ptv = pram[taddr] if pram[taddr] is not None else 0xFF
        default_tris = 0x3F if pname == "PORTA" else (0x07 if pname == "PORTE" else 0xFF)
        if pname in ("PORTB", "PORTD") or pv != 0 or ppv != 0 or tv != default_tris or ptv != default_tris:
            print(format_cell_row(pname, pv, ppv, f"[0x{paddr:02X} | {fmt_pins(pv)[1:-1]}]"))
            print(format_cell_row(tname, tv, ptv, f"[0x{taddr:02X}]"))

    if last_msg:
        print(f"\n{BOLD}Last Action:{RESET} {last_msg.strip()}")

    print(
        f"\n{BOLD}{YELLOW}Commands:{RESET} "
        f"{BOLD}[Enter]{RESET} Step Over | "
        f"{BOLD}[i]{RESET} Step Into | "
        f"{BOLD}[b <line>]{RESET} Breakpoint | "
        f"{BOLD}[c]{RESET} Continue | "
        f"{BOLD}[r]{RESET} Reset | "
        f"{BOLD}[q]{RESET} Quit"
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: pic16_terminal_debugger.py <file.asm>")
        sys.exit(1)

    asm_path = os.path.abspath(sys.argv[1])
    if not os.path.exists(asm_path) or not asm_path.lower().endswith(".asm"):
        cwd = os.getcwd()
        asm_files = [
            os.path.join(cwd, f)
            for f in os.listdir(cwd)
            if f.lower().endswith(".asm") and os.path.isfile(os.path.join(cwd, f))
        ]
        if asm_files:
            asm_path = max(asm_files, key=os.path.getmtime)
        else:
            print(f"Error: No valid .asm file found ({asm_path})")
            sys.exit(1)

    sim = GpsimController()
    logs = []
    if not sim.load_and_compile(asm_path, logs.append):
        print("".join(logs))
        sys.exit(1)

    with open(asm_path, "r", encoding="utf-8", errors="replace") as f:
        src_lines = f.readlines()

    bp_lines = set()
    last_msg = "[PC=0x0000] Ready. Press Enter to step line-by-line."

    try:
        while True:
            render_dashboard(sim, src_lines, bp_lines, last_msg)
            try:
                cmd = input(f"{BOLD}{GREEN}debug> {RESET}").strip()
            except EOFError:
                break

            if cmd in ("", "s", "n", "next", "step"):
                last_msg = sim.step_over()
            elif cmd in ("i", "in", "into"):
                last_msg = sim.step_into()
            elif cmd in ("c", "cont", "continue", "run"):
                _, last_msg = sim.continue_exec()
            elif cmd in ("r", "reset"):
                sim.reset_sim()
                sim.set_breakpoints(sorted(bp_lines))
                last_msg = "Reset [PC=0x0000]"
            elif cmd.startswith("b ") or cmd.startswith("break "):
                parts = cmd.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    lno = int(parts[1])
                    if lno in bp_lines:
                        bp_lines.remove(lno)
                        sim.set_breakpoints(sorted(bp_lines))
                        last_msg = f"[Line {lno}] Breakpoint removed."
                    else:
                        v = sim.set_breakpoints(sorted(bp_lines | {lno}))
                        snapped = v[-1]["line"] if v else lno
                        bp_lines.add(snapped)
                        sim.set_breakpoints(sorted(bp_lines))
                        last_msg = f"[Line {snapped}] Breakpoint set."
            elif "=" in cmd:
                k, v = cmd.split("=", 1)
                try:
                    new_v = sim.set_value(k.strip(), v.strip())
                    last_msg = f"{k.strip()} = 0x{new_v:02X} | 0d{new_v} | 0b{new_v:08b}"
                except Exception as e:
                    last_msg = f"Error: {e}"
            elif cmd in ("q", "quit", "exit"):
                break
            else:
                last_msg = f"Unknown command: '{cmd}'"
    except KeyboardInterrupt:
        pass
    finally:
        sim.stop_gpsim()
        print("\nDebugger exited.")


if __name__ == "__main__":
    main()
