#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PIC16F877A Assembly Debug Adapter (DAP) for VS Code
Uses gpasm (.lst / .cod) + gpsim for cycle-accurate line-by-line debugging.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

# Special Function Registers (SFR) for PIC16F877A
CORE_SFRS = [
    ("PCL", 0x02),
    ("STATUS", 0x03),
    ("FSR", 0x04),
    ("INDF", 0x00),
    ("PCLATH", 0x0A),
    ("INTCON", 0x0B),
]

PORT_SFRS = [
    ("PORTA", 0x05),
    ("TRISA", 0x85),
    ("PORTB", 0x06),
    ("TRISB", 0x86),
    ("PORTC", 0x07),
    ("TRISC", 0x87),
    ("PORTD", 0x08),
    ("TRISD", 0x88),
    ("PORTE", 0x09),
    ("TRISE", 0x89),
]

PERIPH_SFRS = [
    ("TMR0", 0x01),
    ("OPTION_REG", 0x81),
    ("TMR1L", 0x0E),
    ("TMR1H", 0x0F),
    ("T1CON", 0x10),
    ("TMR2", 0x11),
    ("T2CON", 0x12),
    ("PR2", 0x92),
    ("ADRESH", 0x1E),
    ("ADRESL", 0x9E),
    ("ADCON0", 0x1F),
    ("ADCON1", 0x9F),
    ("PIR1", 0x0C),
    ("PIE1", 0x8C),
    ("TXREG", 0x19),
    ("RCREG", 0x1A),
]

ALL_SFR_MAP = {}
for _name, _addr in CORE_SFRS + PORT_SFRS + PERIPH_SFRS:
    ALL_SFR_MAP[_name.upper()] = _addr


def fmt_val(val, prev_val=None, extra=""):
    """Format an 8-bit value concisely as: 0xHH | 0dNUM | 0bNNNNNNNN [extra]"""
    if val is None:
        return "--"
    val = val & 0xFF
    base = f"0x{val:02X} | 0d{val} | 0b{val:08b}"
    if extra:
        base += f"  {extra}"
    if prev_val is not None and (prev_val & 0xFF) != val:
        base = f"* {base}"
    return base


def fmt_pins(val):
    if val is None:
        return ""
    bits = "".join("●" if (val & (1 << b)) else "○" for b in range(7, -1, -1))
    return f"[{bits}]"


def parse_number(text):
    """Parse assembly or standard number formats: 0x25, 0d10, h'25', b'10101010', d'10', 42."""
    s = text.strip()
    m = re.match(r"^[hH]'([0-9A-Fa-f]+)'$", s)
    if m:
        return int(m.group(1), 16)
    m = re.match(r"^([0-9A-Fa-f]+)[hH]$", s)
    if m:
        return int(m.group(1), 16)
    m = re.match(r"^[bB]'([01_]+)'$", s)
    if m:
        return int(m.group(1).replace("_", ""), 2)
    m = re.match(r"^[dD]'([0-9]+)'$", s)
    if m:
        return int(m.group(1), 10)
    if s.lower().startswith("0d"):
        return int(s[2:], 10)
    if s.lower().startswith("0x"):
        return int(s, 16)
    if s.lower().startswith("0b"):
        return int(s, 2)
    return int(s, 0)


class GpsimController:
    def __init__(self):
        self.proc = None
        self.asm_path = ""
        self.asm_dir = ""
        self.asm_base = ""
        self.cod_path = ""
        self.lst_path = ""

        # Mappings from .lst
        self.pc_to_line = {}        # pc -> line_no (1-indexed)
        self.line_to_pcs = {}       # line_no -> [pc1, pc2, ...]
        self.pc_to_inst = {}        # pc -> (opcode, source_text)
        self.user_vars = []         # [(name, addr, line_no)]
        self.user_var_map = {}      # name_upper -> (name, addr, line_no)
        self.labels = {}            # label_name_upper -> (label_name, pc_addr, line_no)

        # Simulator state
        self.curr_state = {"w": 0, "pc": 0, "status": 0x18, "cycles": 0, "ram": [0] * 512}
        self.prev_state = None
        self.step_count = 0

    def load_and_compile(self, asm_path, log_cb):
        self.asm_path = os.path.abspath(asm_path)
        self.asm_dir = os.path.dirname(self.asm_path)
        self.asm_base = os.path.splitext(os.path.basename(self.asm_path))[0]
        self.cod_path = os.path.join(self.asm_dir, f"{self.asm_base}.cod")
        self.lst_path = os.path.join(self.asm_dir, f"{self.asm_base}.lst")

        log_cb(f"Building: gpasm -p 16f877a \"{os.path.basename(self.asm_path)}\"\n")
        res = subprocess.run(
            ["gpasm", "-p", "16f877a", os.path.basename(self.asm_path)],
            cwd=self.asm_dir,
            capture_output=True,
            text=True,
        )
        if res.stdout:
            log_cb(res.stdout)
        if res.stderr:
            log_cb(res.stderr)
        if res.returncode != 0:
            log_cb(f"Build failed! (Exit code: {res.returncode})\n")
            return False

        if not os.path.exists(self.cod_path) or not os.path.exists(self.lst_path):
            log_cb("Failed to generate .cod or .lst file!\n")
            return False

        self._parse_lst()
        return self._start_gpsim()

    def _parse_lst(self):
        self.pc_to_line.clear()
        self.line_to_pcs.clear()
        self.pc_to_inst.clear()
        self.user_vars.clear()
        self.user_var_map.clear()
        self.labels.clear()

        if not os.path.exists(self.lst_path):
            return

        with open(self.lst_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        inst_re = re.compile(
            r"^([0-9A-Fa-f]{4})\s+([0-9A-Fa-f]{4})(?:\s+([0-9A-Fa-f]{4}))?\s+(\d{5})\s+(.*)$"
        )
        label_re = re.compile(
            r"^([0-9A-Fa-f]{4})\s+(\d{5})\s+([A-Za-z_][A-Za-z0-9_]*):?(?:\s*;.*|\s*)$"
        )
        equ_re = re.compile(
            r"^\s+([0-9A-Fa-f]{8})\s+(\d{5})\s+([A-Za-z_][A-Za-z0-9_]*)\b"
        )

        for raw in lines:
            line = raw.rstrip("\r\n")
            if line.startswith("SYMBOL TABLE"):
                break

            m_inst = inst_re.match(line)
            if m_inst:
                pc = int(m_inst.group(1), 16)
                if pc >= 0x2000:
                    continue
                op1 = int(m_inst.group(2), 16)
                op2_str = m_inst.group(3)
                src_line = int(m_inst.group(4), 10)
                src_text = m_inst.group(5).strip()

                self.pc_to_line[pc] = src_line
                self.line_to_pcs.setdefault(src_line, []).append(pc)
                self.pc_to_inst[pc] = (op1, src_text)

                if op2_str:
                    op2 = int(op2_str, 16)
                    self.pc_to_line[pc + 1] = src_line
                    self.line_to_pcs.setdefault(src_line, []).append(pc + 1)
                    self.pc_to_inst[pc + 1] = (op2, src_text)
                continue

            m_lbl = label_re.match(line)
            if m_lbl:
                pc = int(m_lbl.group(1), 16)
                src_line = int(m_lbl.group(2), 10)
                lbl_name = m_lbl.group(3)
                if pc < 0x2000:
                    self.labels[lbl_name.upper()] = (lbl_name, pc, src_line)
                continue

            m_equ = equ_re.match(line)
            if m_equ:
                val = int(m_equ.group(1), 16)
                src_line = int(m_equ.group(2), 10)
                var_name = m_equ.group(3)
                if var_name.upper() not in ("LIST", "INCLUDE", "ORG", "END", "CBLOCK", "ENDC"):
                    if 0x00 <= val <= 0x1FF:
                        self.user_vars.append((var_name, val, src_line))
                        self.user_var_map[var_name.upper()] = (var_name, val, src_line)

    def _start_gpsim(self):
        self.stop_gpsim()
        self.proc = subprocess.Popen(
            ["gpsim", "-i", "-s", os.path.basename(self.cod_path)],
            cwd=self.asm_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.proc.stdin.write('scope.ch7 = "GPSIM_READY_999"\n')
        self.proc.stdin.flush()
        self._send_cmd("")
        self.step_count = 0
        self.curr_state = self._read_state()
        self.prev_state = dict(self.curr_state)
        self.prev_state["ram"] = list(self.curr_state["ram"])
        return True

    def stop_gpsim(self):
        if self.proc:
            try:
                self.proc.stdin.write("quit\n")
                self.proc.stdin.flush()
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None

    def _send_cmd(self, cmd_str):
        if not self.proc or self.proc.poll() is not None:
            return []
        full = (cmd_str + "\nscope.ch7\n") if cmd_str else "scope.ch7\n"
        self.proc.stdin.write(full)
        self.proc.stdin.flush()
        out = []
        while True:
            line = self.proc.stdout.readline()
            if not line:
                break
            s = line.rstrip("\r\n")
            if s.strip() == "GPSIM_READY_999":
                break
            out.append(s)
        return out

    def _read_state(self):
        lines = self._send_cmd("dump\ncycles")
        ram = list(self.curr_state.get("ram", [0] * 512))
        w = self.curr_state.get("w", 0)
        pc = self.curr_state.get("pc", 0)
        status = self.curr_state.get("status", 0x18)
        cycles = self.curr_state.get("cycles", 0)

        row_re = re.compile(r"^([0-9a-fA-F]{4}):\s+((?:[0-9a-fA-F]{2}|--)(?:\s+(?:[0-9a-fA-F]{2}|--)){15})")
        for line in lines:
            s = line.strip()
            m_row = row_re.match(s)
            if m_row:
                base_addr = int(m_row.group(1), 16)
                cells = m_row.group(2).split()
                for idx, cell in enumerate(cells):
                    if base_addr + idx < 512:
                        ram[base_addr + idx] = None if cell == "--" else int(cell, 16)
                continue

            if s.startswith("W ="):
                try:
                    w = int(s.split("=")[1].strip(), 16)
                except ValueError:
                    pass
            elif s.startswith("pc ="):
                try:
                    pc = int(s.split("=")[1].strip(), 16)
                except ValueError:
                    pass
            elif "= 0x" in s and not s.startswith("0x"):
                parts = s.split("=")
                if len(parts) == 2:
                    try:
                        cycles = int(parts[1].strip(), 16)
                    except ValueError:
                        pass

        if ram[0x03] is not None:
            status = ram[0x03]
        return {"w": w, "pc": pc, "status": status, "cycles": cycles, "ram": ram}

    def set_breakpoints(self, req_lines):
        out = self._send_cmd("break")
        for line in out:
            m = re.match(r"^\s*(\d+):\s+p16\w+\s+Execution", line)
            if m:
                self._send_cmd(f"clear {m.group(1)}")

        verified_bps = []
        sorted_exec_lines = sorted(self.line_to_pcs.keys())
        for req_line in req_lines:
            snapped = None
            for el in sorted_exec_lines:
                if el >= req_line:
                    snapped = el
                    break
            if snapped is None and sorted_exec_lines:
                snapped = sorted_exec_lines[-1]

            if snapped is not None:
                pc = self.line_to_pcs[snapped][0]
                self._send_cmd(f"break e 0x{pc:04X}")
                verified_bps.append({"verified": True, "line": snapped})
            else:
                verified_bps.append({"verified": False, "line": req_line})
        return verified_bps

    def _save_prev(self):
        self.prev_state = {
            "w": self.curr_state["w"],
            "pc": self.curr_state["pc"],
            "status": self.curr_state["status"],
            "cycles": self.curr_state["cycles"],
            "ram": list(self.curr_state["ram"]),
        }

    def step_into(self):
        self._save_prev()
        old_pc = self.curr_state["pc"]
        old_line = self.pc_to_line.get(old_pc)

        self._send_cmd("step")
        self.curr_state = self._read_state()

        new_pc = self.curr_state["pc"]
        if (
            old_line is not None
            and new_pc == old_pc + 1
            and self.pc_to_line.get(new_pc) == old_line
        ):
            self._send_cmd("step")
            self.curr_state = self._read_state()

        self.step_count += 1
        return self._format_step_summary(old_pc)

    def step_over(self):
        self._save_prev()
        old_pc = self.curr_state["pc"]
        old_line = self.pc_to_line.get(old_pc)
        opcode, _ = self.pc_to_inst.get(old_pc, (0, ""))

        if (opcode & 0x3800) == 0x2000:
            self._send_cmd("step over")
            self.curr_state = self._read_state()
        else:
            self._send_cmd("step")
            self.curr_state = self._read_state()
            new_pc = self.curr_state["pc"]
            if (
                old_line is not None
                and new_pc == old_pc + 1
                and self.pc_to_line.get(new_pc) == old_line
            ):
                self._send_cmd("step")
                self.curr_state = self._read_state()

        self.step_count += 1
        return self._format_step_summary(old_pc)

    def continue_exec(self):
        self._save_prev()
        old_pc = self.curr_state["pc"]
        opcode, _ = self.pc_to_inst.get(old_pc, (0, ""))

        if opcode == (0x2800 | (old_pc & 0x7FF)):
            return "pause", f"End-of-program loop [PC=0x{old_pc:04X}]\n"

        target_cycles = self.curr_state["cycles"] + 500000
        self._send_cmd(f"break c 0x{target_cycles:X}")
        self._send_cmd("run")

        out = self._send_cmd("break")
        for line in out:
            m = re.match(r"^\s*(\d+):\s+.*Cycle", line, re.IGNORECASE)
            if m:
                self._send_cmd(f"clear {m.group(1)}")

        self.curr_state = self._read_state()
        self.step_count += 1
        return "breakpoint", self._format_step_summary(old_pc)

    def reset_sim(self):
        self._send_cmd("reset")
        self.step_count = 0
        self.curr_state = self._read_state()
        self.prev_state = dict(self.curr_state)
        self.prev_state["ram"] = list(self.curr_state["ram"])

    def set_value(self, name, raw_val):
        val = parse_number(raw_val) & 0xFF
        uname = name.split("[")[0].split("(")[0].strip().upper()
        if uname == "W":
            self._send_cmd(f"p16f877a.W = 0x{val:02X}")
        elif uname in self.user_var_map:
            _, addr, _ = self.user_var_map[uname]
            self._send_cmd(f"p16f877a.ramData[0x{addr:03X}] = 0x{val:02X}")
        elif uname in ALL_SFR_MAP:
            addr = ALL_SFR_MAP[uname]
            self._send_cmd(f"p16f877a.ramData[0x{addr:03X}] = 0x{val:02X}")
        elif uname.startswith("0X"):
            addr = int(uname, 16)
            self._send_cmd(f"p16f877a.ramData[0x{addr:03X}] = 0x{val:02X}")
        self.curr_state = self._read_state()
        return val

    def _format_step_summary(self, old_pc):
        old_line = self.pc_to_line.get(old_pc, "?")
        _, src_text = self.pc_to_inst.get(old_pc, (0, ""))
        new_pc = self.curr_state["pc"]
        new_line = self.pc_to_line.get(new_pc, "?")

        diffs = []
        if self.prev_state:
            if self.curr_state["w"] != self.prev_state["w"]:
                nw = self.curr_state["w"]
                diffs.append(f"W: 0x{nw:02X} | 0d{nw} | 0b{nw:08b}")
            if self.curr_state["status"] != self.prev_state["status"]:
                st = self.curr_state["status"]
                z = (st >> 2) & 1
                dc = (st >> 1) & 1
                c = st & 1
                bank = (st >> 5) & 3
                diffs.append(f"STATUS: 0x{st:02X} [Bank {bank} | Z={z} DC={dc} C={c}]")

            watched_addrs = {}
            for vname, vaddr, _ in self.user_vars:
                watched_addrs[vaddr] = vname
            for sname, saddr in PORT_SFRS + PERIPH_SFRS + CORE_SFRS:
                if sname not in ("STATUS", "PCL"):
                    watched_addrs.setdefault(saddr, sname)

            for addr, label in sorted(watched_addrs.items()):
                old_v = self.prev_state["ram"][addr]
                new_v = self.curr_state["ram"][addr]
                if old_v is not None and new_v is not None and old_v != new_v:
                    diffs.append(f"{label}: 0x{new_v:02X} | 0d{new_v} | 0b{new_v:08b}")

        diff_str = " -> " + " , ".join(diffs) if diffs else ""
        return f"[{self.step_count:02d} | Line {old_line}->{new_line} | 0x{old_pc:04X}] {src_text}{diff_str}\n"


class DebugAdapterServer:
    def __init__(self, in_stream, out_stream):
        self.in_stream = in_stream
        self.out_stream = out_stream
        self.seq = 1
        self.lock = threading.Lock()
        self.sim = GpsimController()

    def send_msg(self, msg):
        with self.lock:
            msg["seq"] = self.seq
            self.seq += 1
            body = json.dumps(msg).encode("utf-8")
            header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
            self.out_stream.write(header + body)
            self.out_stream.flush()

    def send_response(self, req, body=None, success=True, message=None):
        resp = {
            "type": "response",
            "request_seq": req["seq"],
            "command": req["command"],
            "success": success,
        }
        if body is not None:
            resp["body"] = body
        if message is not None:
            resp["message"] = message
        self.send_msg(resp)

    def send_event(self, event_name, body=None):
        ev = {"type": "event", "event": event_name}
        if body is not None:
            ev["body"] = body
        self.send_msg(ev)

    def log_console(self, text, category="console"):
        self.send_event("output", {"category": category, "output": text})

    def serve_forever(self):
        while True:
            headers = {}
            while True:
                line = self.in_stream.readline()
                if not line:
                    return
                line_str = line.decode("ascii", errors="replace").strip()
                if not line_str:
                    break
                if ":" in line_str:
                    k, v = line_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            length = int(headers.get("content-length", 0))
            if length <= 0:
                continue
            body_bytes = self.in_stream.read(length)
            if not body_bytes:
                return
            msg = json.loads(body_bytes.decode("utf-8", errors="replace"))
            if msg.get("type") == "request":
                self.handle_request(msg)

    def handle_request(self, req):
        cmd = req["command"]
        args = req.get("arguments", {})

        if cmd == "initialize":
            self.send_response(
                req,
                {
                    "supportsConfigurationDoneRequest": True,
                    "supportsEvaluateForHovers": True,
                    "supportsSetVariable": True,
                    "supportsRestartRequest": True,
                    "supportsSingleThreadExecutionRequests": True,
                },
            )
            self.send_event("initialized")

        elif cmd == "launch":
            prog = args.get("program", "")
            default_ws = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cwd = args.get("cwd", "") or default_ws
            if not os.path.isdir(cwd):
                cwd = default_ws
            if not prog or not prog.lower().endswith(".asm") or not os.path.exists(prog):
                asm_files = [
                    os.path.join(cwd, f)
                    for f in os.listdir(cwd)
                    if f.lower().endswith(".asm") and os.path.isfile(os.path.join(cwd, f))
                ]
                if asm_files:
                    prog = max(asm_files, key=os.path.getmtime)

            if not prog or not os.path.exists(prog):
                self.send_response(req, success=False, message="Please open a .asm file first!")
                return

            ok = self.sim.load_and_compile(prog, self.log_console)
            if not ok:
                self.send_response(req, success=False, message="gpasm build failed!")
                return

            var_names = ", ".join(f"{n}[0x{a:02X}]" for n, a, _ in self.sim.user_vars) or "None"
            self.log_console(
                f"Debugger Ready: {os.path.basename(prog)} | Variables: {var_names}\n"
            )
            self.send_response(req)

        elif cmd == "setBreakpoints":
            bps = args.get("breakpoints", [])
            req_lines = [bp.get("line", 1) for bp in bps]
            verified = self.sim.set_breakpoints(req_lines)
            self.send_response(req, {"breakpoints": verified})

        elif cmd == "configurationDone":
            self.send_response(req)
            self.send_event("stopped", {"reason": "entry", "threadId": 1})

        elif cmd == "threads":
            self.send_response(req, {"threads": [{"id": 1, "name": "PIC16F877A"}]})

        elif cmd == "stackTrace":
            pc = self.sim.curr_state["pc"]
            line = self.sim.pc_to_line.get(pc, 1)
            _, inst_txt = self.sim.pc_to_inst.get(pc, (0, "ORG 0x00"))
            frame = {
                "id": 1,
                "name": f"0x{pc:04X} | {inst_txt}",
                "source": {
                    "name": os.path.basename(self.sim.asm_path),
                    "path": self.sim.asm_path,
                },
                "line": line,
                "column": 1,
            }
            self.send_response(req, {"stackFrames": [frame], "totalFrames": 1})

        elif cmd == "scopes":
            scopes = [
                {
                    "name": "1. Core Registers",
                    "variablesReference": 1,
                    "expensive": False,
                },
                {
                    "name": "2. User Variables",
                    "variablesReference": 2,
                    "expensive": False,
                },
                {
                    "name": "3. Ports & TRIS",
                    "variablesReference": 3,
                    "expensive": False,
                },
                {
                    "name": "4. Special Function Registers (SFR)",
                    "variablesReference": 4,
                    "expensive": False,
                },
                {
                    "name": "5. RAM Memory",
                    "variablesReference": 5,
                    "expensive": False,
                },
            ]
            self.send_response(req, {"scopes": scopes})

        elif cmd == "variables":
            vref = args.get("variablesReference", 0)
            variables = self._build_variables(vref)
            self.send_response(req, {"variables": variables})

        elif cmd == "next":
            msg = self.sim.step_over()
            self.log_console(msg)
            self.send_response(req)
            self.send_event("stopped", {"reason": "step", "threadId": 1})

        elif cmd in ("stepIn", "stepOut"):
            msg = self.sim.step_into()
            self.log_console(msg)
            self.send_response(req)
            self.send_event("stopped", {"reason": "step", "threadId": 1})

        elif cmd == "continue":
            reason, msg = self.sim.continue_exec()
            self.log_console(msg)
            self.send_response(req, {"allThreadsContinued": True})
            self.send_event("stopped", {"reason": reason, "threadId": 1})

        elif cmd == "pause":
            self.send_response(req)
            self.send_event("stopped", {"reason": "pause", "threadId": 1})

        elif cmd == "restart":
            self.sim.load_and_compile(self.sim.asm_path, self.log_console)
            self.log_console("Reset [PC=0x0000]\n")
            self.send_response(req)
            self.send_event("stopped", {"reason": "entry", "threadId": 1})

        elif cmd == "setVariable":
            name = args.get("name", "")
            value = args.get("value", "0")
            try:
                new_val = self.sim.set_value(name, value)
                self.send_response(req, {"value": fmt_val(new_val)})
            except Exception as e:
                self.send_response(req, success=False, message=f"Invalid value: {e}")

        elif cmd == "evaluate":
            expr = args.get("expression", "").strip()
            res_str = self._evaluate_expr(expr)
            if res_str is not None:
                self.send_response(req, {"result": res_str, "variablesReference": 0})
            else:
                self.send_response(req, {"result": "", "variablesReference": 0})

        elif cmd in ("disconnect", "terminate"):
            self.sim.stop_gpsim()
            self.send_response(req)
            self.send_event("terminated")

        else:
            self.send_response(req)

    def _build_variables(self, vref):
        st = self.sim.curr_state
        prev = self.sim.prev_state or st
        ram = st["ram"]
        pram = prev["ram"]
        res = []

        if vref == 1:
            # 1. Core Registers
            res.append(
                {
                    "name": "W",
                    "value": fmt_val(st["w"], prev["w"]),
                    "variablesReference": 0,
                }
            )

            status = st["status"]
            pstatus = prev["status"]
            bank = (status >> 5) & 0x03
            z = (status >> 2) & 1
            dc = (status >> 1) & 1
            c = status & 1
            res.append(
                {
                    "name": "STATUS",
                    "value": fmt_val(status, pstatus, f"[0x03 | Bank {bank} | Z={z} DC={dc} C={c}]"),
                    "variablesReference": 101,
                }
            )

            pc = st["pc"]
            line = self.sim.pc_to_line.get(pc, "?")
            res.append(
                {
                    "name": "PC",
                    "value": f"0x{pc:04X} | 0d{pc}  [Line {line}]",
                    "variablesReference": 0,
                }
            )

            cyc = st["cycles"]
            res.append(
                {
                    "name": "Cycles",
                    "value": f"0d{cyc}  [{cyc} µs]",
                    "variablesReference": 0,
                }
            )

            for sname, saddr in CORE_SFRS:
                if sname == "STATUS":
                    continue
                if sname == "INDF":
                    fsr_val = ram[0x04] or 0
                    irp = (status >> 7) & 1
                    eff_addr = (irp << 8) | fsr_val
                    indf_val = ram[eff_addr] if eff_addr < 512 else 0
                    res.append(
                        {
                            "name": "INDF",
                            "value": fmt_val(indf_val, None, f"[@0x{eff_addr:03X}]"),
                            "variablesReference": 0,
                        }
                    )
                else:
                    res.append(
                        {
                            "name": sname,
                            "value": fmt_val(ram[saddr], pram[saddr], f"[0x{saddr:02X}]"),
                            "variablesReference": 0,
                        }
                    )

        elif vref == 101:
            # STATUS bit breakdown
            status = st["status"]
            irp = (status >> 7) & 1
            rp1 = (status >> 6) & 1
            rp0 = (status >> 5) & 1
            bank = (status >> 5) & 3
            to = (status >> 4) & 1
            pd = (status >> 3) & 1
            z = (status >> 2) & 1
            dc = (status >> 1) & 1
            c = status & 1
            res.extend(
                [
                    {"name": "RP1:RP0", "value": f"0b{rp1}{rp0}  [Bank {bank}]", "variablesReference": 0},
                    {"name": "Z", "value": f"{z}  [Zero]", "variablesReference": 0},
                    {"name": "C", "value": f"{c}  [Carry]", "variablesReference": 0},
                    {"name": "DC", "value": f"{dc}  [Digit Carry]", "variablesReference": 0},
                    {"name": "IRP", "value": f"{irp}", "variablesReference": 0},
                    {"name": "TO:PD", "value": f"{to}:{pd}", "variablesReference": 0},
                ]
            )

        elif vref == 2:
            # 2. User Variables (EQU / CBLOCK)
            if not self.sim.user_vars:
                res.append(
                    {
                        "name": "-",
                        "value": "[No user variables defined]",
                        "variablesReference": 0,
                    }
                )
            else:
                for vname, vaddr, _ in self.sim.user_vars:
                    val = ram[vaddr] if vaddr < 512 else 0
                    pval = pram[vaddr] if vaddr < 512 else 0
                    bank_no = vaddr >> 7
                    res.append(
                        {
                            "name": vname,
                            "value": fmt_val(val, pval, f"[0x{vaddr:02X} | Bank {bank_no}]"),
                            "variablesReference": 0,
                        }
                    )

        elif vref == 3:
            # 3. Ports & TRIS
            for sname, saddr in PORT_SFRS:
                val = ram[saddr]
                pval = pram[saddr]
                extra = f"[0x{saddr:02X} | {fmt_pins(val)[1:-1]}]" if sname.startswith("PORT") else f"[0x{saddr:02X}]"
                res.append(
                    {
                        "name": sname,
                        "value": fmt_val(val, pval, extra),
                        "variablesReference": 0,
                    }
                )

        elif vref == 4:
            # 4. Special Function Registers (SFR)
            for sname, saddr in PERIPH_SFRS:
                val = ram[saddr]
                pval = pram[saddr]
                res.append(
                    {
                        "name": sname,
                        "value": fmt_val(val, pval, f"[0x{saddr:02X}]"),
                        "variablesReference": 0,
                    }
                )

        elif vref == 5:
            # 5. RAM Memory
            gpr_ranges = [
                (0, 0x020, 0x07F),
                (1, 0x0A0, 0x0EF),
                (2, 0x110, 0x16F),
                (3, 0x190, 0x1EF),
            ]
            var_by_addr = {vaddr: vname for vname, vaddr, _ in self.sim.user_vars}
            non_zero_count = 0
            for bank_idx, start_a, end_a in gpr_ranges:
                for addr in range(start_a, end_a + 1):
                    v = ram[addr]
                    pv = pram[addr]
                    if (v is not None and v != 0) or (pv is not None and pv != v):
                        non_zero_count += 1
                        info = f"[{var_by_addr[addr]} | Bank {bank_idx}]" if addr in var_by_addr else f"[Bank {bank_idx}]"
                        res.append(
                            {
                                "name": f"0x{addr:03X}",
                                "value": fmt_val(v, pv, info),
                                "variablesReference": 0,
                            }
                        )
            if non_zero_count == 0:
                res.append(
                    {
                        "name": "-",
                        "value": "[All GPR addresses are 0x00]",
                        "variablesReference": 0,
                    }
                )
            for bank_idx, start_a, end_a in gpr_ranges:
                res.append(
                    {
                        "name": f"Bank {bank_idx}",
                        "value": f"[0x{start_a:03X} - 0x{end_a:03X}]",
                        "variablesReference": 500 + bank_idx,
                    }
                )

        elif 500 <= vref <= 503:
            bank_idx = vref - 500
            ranges = {
                0: (0x020, 0x07F),
                1: (0x0A0, 0x0EF),
                2: (0x110, 0x16F),
                3: (0x190, 0x1EF),
            }
            start_a, end_a = ranges[bank_idx]
            var_by_addr = {vaddr: vname for vname, vaddr, _ in self.sim.user_vars}
            for addr in range(start_a, end_a + 1):
                v = ram[addr]
                pv = pram[addr]
                info = f"[{var_by_addr[addr]}]" if addr in var_by_addr else ""
                res.append(
                    {
                        "name": f"0x{addr:03X}",
                        "value": fmt_val(v, pv, info),
                        "variablesReference": 0,
                    }
                )

        return res

    def _evaluate_expr(self, expr):
        if not expr:
            return None
        u = expr.upper()
        st = self.sim.curr_state
        ram = st["ram"]

        if u in ("W", "WREG"):
            return fmt_val(st["w"])
        if u == "PC":
            return f"0x{st['pc']:04X} | 0d{st['pc']}"
        if u == "STATUS":
            s = st["status"]
            return fmt_val(s, extra=f"[0x03 | Bank {(s >> 5) & 3} | Z={(s >> 2) & 1} DC={(s >> 1) & 1} C={s & 1}]")
        if u == "Z":
            return f"{(st['status'] >> 2) & 1}  [STATUS.Z]"
        if u == "C":
            return f"{st['status'] & 1}  [STATUS.C]"
        if u == "DC":
            return f"{(st['status'] >> 1) & 1}  [STATUS.DC]"
        if u == "RP0":
            return f"{(st['status'] >> 5) & 1}  [STATUS.RP0]"
        if u == "RP1":
            return f"{(st['status'] >> 6) & 1}  [STATUS.RP1]"

        if u in self.sim.user_var_map:
            _, vaddr, _ = self.sim.user_var_map[u]
            return fmt_val(ram[vaddr], extra=f"[0x{vaddr:02X}]")

        if u in ALL_SFR_MAP:
            saddr = ALL_SFR_MAP[u]
            extra = f"[0x{saddr:02X} | {fmt_pins(ram[saddr])[1:-1]}]" if u.startswith("PORT") else f"[0x{saddr:02X}]"
            return fmt_val(ram[saddr], extra=extra)

        if u in self.sim.labels:
            _, lpc, lline = self.sim.labels[u]
            return f"0x{lpc:04X}  [Line {lline}]"

        try:
            addr = parse_number(expr)
            if 0 <= addr < 512:
                return fmt_val(ram[addr], extra=f"[0x{addr:03X}]")
        except Exception:
            pass
        return None


def handle_client(conn):
    try:
        subprocess.run(
            [sys.executable, os.path.abspath(__file__)],
            stdin=conn.fileno(),
            stdout=conn.fileno(),
        )
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def kill_old_daemons():
    my_pid = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == my_pid:
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                cmd = f.read().decode("utf-8", errors="replace")
            if "pic16_debug_adapter.py" in cmd and ("--daemon" in cmd or "--server" in cmd):
                os.kill(pid, 15)
        except Exception:
            pass


def run_tcp_server(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind(("127.0.0.1", port))
    except OSError:
        sys.exit(0)
    srv.listen(5)
    while True:
        conn, _ = srv.accept()
        t = threading.Thread(target=handle_client, args=(conn,), daemon=True)
        t.start()


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--daemon":
        port = int(sys.argv[2])
        kill_old_daemons()
        time.sleep(0.05)

        pid = os.fork()
        if pid > 0:
            for _ in range(25):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    s.close()
                    break
                s.close()
                time.sleep(0.02)
            sys.exit(0)

        os.setsid()
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        if devnull > 2:
            os.close(devnull)
        run_tcp_server(port)

    elif len(sys.argv) >= 3 and sys.argv[1] == "--server":
        port = int(sys.argv[2])
        run_tcp_server(port)
    else:
        adapter = DebugAdapterServer(sys.stdin.buffer, sys.stdout.buffer)
        adapter.serve_forever()


if __name__ == "__main__":
    main()
