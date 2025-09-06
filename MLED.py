#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MLED RS232 Terminal GUI
pip3 install pyserial
python3 mled_terminal.py
"""

import sys
import time
import unicodedata
from typing import Optional, Callable
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports

STX = 0x02
LF  = 0x0A

BAUDRATE = 9600
BYTESIZE = serial.EIGHTBITS
PARITY   = serial.PARITY_NONE
STOPBITS = serial.STOPBITS_ONE

LINE_CHOICES = [str(i) for i in range(1, 16)]

COLOR_MAP = {
    "Default": None,
    "Red": 1, "Green": 2, "Blue": 3, "Yellow": 4, "Magenta": 5,
    "Cyan": 6, "White": 7, "Orange": 8, "Deep pink": 9, "Light Blue": 10,
}

# intensywne kolory przycisków
GREEN_BG = "#22c55e"; GREEN_HOVER = "#16a34a"; GREEN_ACTIVE = "#15803d"
RED_BG   = "#ef4444"; RED_HOVER   = "#dc2626"; RED_ACTIVE   = "#b91c1c"
BLUE_BG  = "#3b82f6"; BLUE_HOVER  = "#2563eb"; BLUE_ACTIVE  = "#1d4ed8"
GRAY_BG  = "#9ca3af"; GRAY_HOVER  = "#a8afb7"; GRAY_ACTIVE  = "#cbd5e1"

# ---------- Rounded button ----------
class RoundButton(tk.Canvas):
    def __init__(self, master, text: str, command: Optional[Callable] = None,
                 bg=BLUE_BG, fg="#000000", hover=BLUE_HOVER, active=BLUE_ACTIVE,
                 padding_x=18, padding_y=10, radius=14, font=("Helvetica", 13, "bold"),
                 ambient: Optional[str] = None, **kwargs):
        self._bg_color = bg
        self._fg_color = fg
        self._hover = hover
        self._active = active
        self._radius = radius
        self._padx = padding_x
        self._pady = padding_y
        self._text = text
        self._command = command
        self._font = font
        self._force_width: Optional[int] = None

        if ambient is None:
            try:
                ambient = master.cget("background")
            except Exception:
                ambient = "#242424"

        super().__init__(master, highlightthickness=0, bg=ambient, bd=0, **kwargs)
        self._enabled = True
        self._draw(self._bg_color)
        self.bind("<Enter>", lambda e: self._redraw(self._hover))
        self.bind("<Leave>", lambda e: self._redraw(self._bg_color))
        self.bind("<ButtonPress-1>", lambda e: self._redraw(self._active))
        self.bind("<ButtonRelease-1>", self._on_release)

    def _pill(self, w, h, r, fill):
        self.create_rectangle(r, 0, w - r, h, fill=fill, outline="")
        self.create_rectangle(0, r, w, h - r, fill=fill, outline="")
        self.create_oval(0, 0, 2 * r, 2 * r, fill=fill, outline="")
        self.create_oval(w - 2 * r, 0, w, 2 * r, fill=fill, outline="")
        self.create_oval(0, h - 2 * r, 2 * r, h, fill=fill, outline="")
        self.create_oval(w - 2 * r, h - 2 * r, w, h, fill=fill, outline="")

    def _draw(self, fill):
        self.delete("all")
        tmp = self.create_text(0, 0, text=self._text, fill=self._fg_color, font=self._font, anchor="nw")
        bbox = self.bbox(tmp)
        w_text = (bbox[2] - bbox[0]) + 2 * self._padx
        h = (bbox[3] - bbox[1]) + 2 * self._pady
        self.delete(tmp)
        w = max(w_text, self._force_width or 0) or w_text
        self.config(width=w, height=h)
        r = min(self._radius, h // 2, w // 2)
        self._pill(w, h, r, fill)
        self.create_text(w // 2, h // 2, text=self._text, fill=self._fg_color, font=self._font, anchor="c")

    def _redraw(self, fill):
        self._draw(fill)

    def _on_release(self, _):
        if not self._enabled:
            return
        self._redraw(self._hover)
        if callable(self._command):
            self.after(1, self._command)

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self._fg_color = "#9ca3af" if not enabled else "#000000"
        self._draw(self._bg_color)

    def stretch_fraction(self, parent, frac: float = 1.0):
        def on_conf(e):
            self._force_width = int(e.width * frac)
            self._draw(self._bg_color)
        parent.bind("<Configure>", on_conf)

# ---------- App ----------
class MLEDTerminal(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MLED RS232 Terminal")
        self.geometry("1100x840")
        self.resizable(False, False)

        self.bg = "#242424"
        self.card = "#2f2f2f"
        self.fg = "#e5e7eb"
        self.subfg = "#cbd5e1"
        self.configure(bg=self.bg)

        self.port = None

        # pasek statusu
        self.conn_bar = tk.Frame(self, height=22, bg="#5b5b5b")
        self.conn_bar.pack(fill=tk.X, side=tk.TOP)
        self.conn_label = tk.Label(self.conn_bar, text="Disconnected", fg="white", bg="#5b5b5b", font=("Helvetica", 12, "bold"))
        self.conn_label.pack(side=tk.LEFT, padx=10, pady=2)

        # stany
        self.scroll_job = None
        self.scroll_buf = ""
        self.scroll_delay_ms = 300
        self.scroll_temp_prev = None
        self.scroll_len = 0
        self.scroll_idx = 0
        self.scroll_active_color: Optional[int] = None
        self.scroll_rainbow = False

        self.timer_mode = None
        self.timer_start_ts = None
        self.timer_down_end_ts = None
        self.timer_job = None

        self.lock_mode: Optional[str] = None

        # rainbow
        self.rainbow_var = tk.BooleanVar(value=False)
        self.rainbow_codes = [1,2,3,4,5,6,7,8,9,10]
        self.rainbow_idx = 0

        # style ttk
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background=self.bg)
        style.configure("TLabel", background=self.bg, foreground=self.fg)
        style.configure("TEntry", fieldbackground="#111111", background="#111111", foreground=self.fg)
        style.configure("TCombobox", fieldbackground="#111111", background="#111111", foreground=self.fg)
        style.configure("TRadiobutton", background=self.bg, foreground=self.fg)
        style.configure("TCheckbutton", background=self.bg, foreground=self.fg)

        self.build_ui()
        self.set_mode(None)

    # -------- combobox dark ----------
    def style_dark_combobox(self, combo: ttk.Combobox, field_bg: str = "#111111"):
        style = ttk.Style()
        stylename = f"Dark-{id(combo)}.TCombobox"
        style.configure(stylename, fieldbackground=field_bg, background=field_bg,
                        foreground=self.fg, arrowcolor=self.fg)
        style.map(stylename,
                  fieldbackground=[("readonly", field_bg), ("active", field_bg), ("focus", field_bg)],
                  background=[("readonly", field_bg), ("active", field_bg), ("focus", field_bg)],
                  foreground=[("readonly", self.fg), ("active", self.fg), ("focus", self.fg)],
                  selectbackground=[("!disabled", "#374151")],
                  selectforeground=[("!disabled", "#ffffff")],
                  arrowcolor=[("active", self.fg), ("focus", self.fg), ("readonly", self.fg)])
        combo.configure(style=stylename)

    # ---------- serial ----------
    def open_serial(self):
        port_name = self.port_var.get().strip()
        if not port_name:
            messagebox.showerror("Error", "Provide serial port name")
            return
        try:
            self.port = serial.Serial(port=port_name, baudrate=BAUDRATE, bytesize=BYTESIZE,
                                      parity=PARITY, stopbits=STOPBITS, timeout=0.2)
            self.btn_connect.set_enabled(False)
            self.btn_disconnect.set_enabled(True)
            self.set_connected_ui(True, port_name)
            payload = "^ic 5 7^^cs 3^MLED^cs 0^"
            self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), payload))
            self.after(3000, lambda: self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), "")))
        except Exception as e:
            self.port = None
            ports = [p.device for p in serial.tools.list_ports.comports()]
            info = "\nAvailable ports:\n" + ("\n".join(ports) if ports else "none")
            messagebox.showerror("Error", f"Could not open port.\n{e}{info}")
            self.set_connected_ui(False)

    def close_serial(self):
        try:
            if self.port and self.port.is_open:
                self.port.close()
            self.port = None
            self.btn_connect.set_enabled(True)
            self.btn_disconnect.set_enabled(False)
            self.set_connected_ui(False)
        except Exception as e:
            messagebox.showerror("Error", f"Close port problem.\n{e}")

    def set_connected_ui(self, connected: bool, port_name: str = ""):
        if connected:
            self.conn_bar.configure(bg="#22c55e")
            self.conn_label.configure(text=f"Connected to: {port_name}", bg="#22c55e", fg="#062b14")
        else:
            self.conn_bar.configure(bg="#5b5b5b")
            self.conn_label.configure(text="Disconnected", bg="#5b5b5b", fg="white")

    def send_bytes(self, data: bytes):
        if not self.port or not self.port.is_open:
            messagebox.showwarning("Warning", "Not connected")
            return
        try:
            self.port.write(data)
        except Exception as e:
            messagebox.showerror("Error", f"Write failed.\n{e}")

    # ---------- frames ----------
    def build_frame(self, line_char: str, brightness: str, payload: str) -> bytes:
        if brightness not in ["1", "2", "3"]:
            raise ValueError("Brightness must be 1 2 or 3")
        if len(payload) > 64:
            raise ValueError("Too long. Max 64 characters")
        b = bytearray()
        b.append(STX)
        b.extend(line_char.encode("ascii"))
        b.extend(brightness.encode("ascii"))
        b.extend(payload.encode("latin-1"))
        b.append(LF)
        return bytes(b)

    def wrap_color(self, text: str, color_code: Optional[int]) -> str:
        return text if color_code is None else f"^cs {color_code}^{text}^cs 0^"

    # transliteracja
    def sanitize(self, text: str) -> str:
        base_map = {
            'ą':'a','ć':'c','ę':'e','ł':'l','ń':'n','ó':'o','ś':'s','ż':'z','ź':'z',
            'Ą':'A','Ć':'C','Ę':'E','Ł':'L','Ń':'N','Ó':'O','Ś':'S','Ż':'Z','Ź':'Z',
            'ß':'ss','Æ':'AE','æ':'ae','Œ':'OE','œ':'oe'
        }
        out = []
        for ch in text:
            if ch == '^':
                out.append('*'); continue
            ch = base_map.get(ch, ch)
            deacc = ''.join(c for c in unicodedata.normalize('NFKD', ch) if not unicodedata.combining(c))
            for c in deacc:
                try:
                    c.encode('latin-1')
                    o = ord(c)
                    if 32 <= o <= 126 or 224 <= o <= 255:
                        out.append(c)
                    else:
                        out.append('*')
                except Exception:
                    out.append('*')
        return ''.join(out)

    def cmd_rt(self, flags: int, fmt_text: str) -> str:
        return f"^rt {flags} {fmt_text}^"

    # ---------- scrolling ----------
    def start_scroll(self, text: str, color_override: Optional[int] = None, rainbow_cycle: bool = False):
        self.stop_scroll()
        text = self.sanitize(text)
        base = text if len(text) <= 64 else text[:64]
        self.scroll_buf = base + "   "
        speed = int(self.scroll_speed_var.get())
        delay_map = {1: 550, 2: 350, 3: 220}
        self.scroll_delay_ms = delay_map.get(speed, 550)
        self.scroll_active_color = color_override
        self.scroll_len = len(self.scroll_buf)
        self.scroll_idx = 0
        self.scroll_rainbow = bool(rainbow_cycle)
        if speed == 0:
            self._send_plain(base, color_override); return
        self.scroll_step()

    def scroll_step(self):
        if not self.scroll_buf:
            return
        self.scroll_buf = self.scroll_buf[1:] + self.scroll_buf[0]
        self._send_plain(self.scroll_buf[:64], self.scroll_active_color)
        self.scroll_idx = (self.scroll_idx + 1) % max(1, self.scroll_len)
        if self.scroll_rainbow and self.scroll_idx == 0:
            self.scroll_active_color = self.next_rainbow_color()
        self.scroll_job = self.after(self.scroll_delay_ms, self.scroll_step)

    def stop_scroll(self):
        if self.scroll_job is not None:
            try: self.after_cancel(self.scroll_job)
            except Exception: pass
            self.scroll_job = None
        self.scroll_buf = ""
        self.scroll_len = 0
        self.scroll_idx = 0
        self.scroll_active_color = None
        self.scroll_rainbow = False

    def _send_plain(self, text: str, color_override: Optional[int] = None):
        code = color_override
        if code is None:
            code = COLOR_MAP.get(self.text_color_var.get())
        s = self.sanitize(text)
        payload = self.wrap_color(s, code)
        try:
            frame = self.build_frame(self.line_var.get(), self.brightness_var.get(), payload)
        except ValueError as e:
            if "Too long" in str(e):
                overhead = 0 if code is None else (len(f"^cs {code}^") + len("^cs 0^"))
                allowed = max(0, 64 - overhead)
                s2 = s[:allowed]
                payload = self.wrap_color(s2, code)
                frame = self.build_frame(self.line_var.get(), self.brightness_var.get(), payload)
            else:
                raise
        self.send_bytes(frame)

    # ---------- timer tick ----------
    def stop_timer_job(self):
        if self.timer_job is not None:
            try: self.after_cancel(self.timer_job)
            except Exception: pass
            self.timer_job = None

    def tick_timer_up(self):
        if self.timer_mode != 'up' or self.timer_start_ts is None:
            return
        now = time.time()
        elapsed = max(0.0, now - self.timer_start_ts)
        mm = int(elapsed // 60)
        ss_full = elapsed % 60
        ss = int(ss_full)
        cc = int((ss_full - ss) * 100)
        txt = f"{ss:02d}.{cc:02d}" if mm == 0 else f"{mm:02d}:{ss:02d}.{cc:02d}"
        payload = self.wrap_color(txt, COLOR_MAP[self.up_color_var.get()])
        self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), payload))
        self.timer_job = self.after(100, self.tick_timer_up)

    # ---------- countdown finish ----------
    def on_countdown_finished(self):
        self.stop_timer_job()
        msg = (self.down_finish_text_var.get() or "").strip()
        if not msg:
            return
        msg = self.sanitize(msg)[:30]
        color_code = COLOR_MAP[self.down_color_var.get()]
        show_secs = max(1, min(180, int(self.down_finish_secs_var.get() or 1)))
        flash_on = bool(self.down_flash_var.get())

        if len(msg) <= 8:
            if flash_on:
                # miganie fragmentu
                if color_code is None:
                    payload = f"^fs 0 1^" + msg + "^fe^"
                else:
                    payload = f"^fs 0 1 {color_code}^" + msg + "^fe^"
            else:
                payload = self.wrap_color(msg, color_code)
            self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), payload))

            def _clear():
                self.timer_job = None
                self.action_clear_line()
            self.timer_job = self.after(show_secs * 1000, _clear)
        else:
            # dłuższy tekst -> auto scroll 1, opcjonalnie flash całej linii
            if flash_on:
                fd = f"^fd 0 1 {color_code}^" if color_code is not None else "^fd 0 1^"
                self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), fd))
            self.scroll_temp_prev = self.scroll_speed_var.get()
            prev_text_color = self.text_color_var.get()
            self.scroll_speed_var.set("1")
            self.text_color_var.set(self.down_color_var.get())
            self.start_scroll(msg, color_override=color_code, rainbow_cycle=False)

            def _stop_scroll_and_clear():
                self.timer_job = None
                self.action_clear_line()
                if self.scroll_temp_prev is not None:
                    self.scroll_speed_var.set(self.scroll_temp_prev)
                    self.scroll_temp_prev = None
                self.text_color_var.set(prev_text_color)
            self.timer_job = self.after(show_secs * 1000, _stop_scroll_and_clear)

    # ---------- blokady ----------
    def set_mode(self, mode: Optional[str]):
        self.lock_mode = mode
        text_enabled = (mode in (None, "text"))
        self.btn_send.set_enabled(text_enabled)
        for child in self.rb_scroll_children:
            try:
                child.configure(state=("normal" if text_enabled else "disabled"))
            except Exception:
                pass
        up_enabled = (mode in (None, "up"))
        self.btn_up_start.set_enabled(up_enabled)
        self.btn_up_stop.set_enabled(up_enabled)
        down_enabled = (mode in (None, "down"))
        self.btn_down_start.set_enabled(down_enabled)
        self.btn_down_stop.set_enabled(down_enabled)
        self.btn_clear_bottom.set_enabled(True)

    # ---------- rainbow ----------
    def next_rainbow_color(self) -> int:
        code = self.rainbow_codes[self.rainbow_idx]
        self.rainbow_idx = (self.rainbow_idx + 1) % len(self.rainbow_codes)
        return code

    def on_toggle_rainbow(self):
        if self.rainbow_var.get():
            self.scroll_speed_var.set("1")
            try:
                self.rb_scroll_children[0].configure(state="disabled")  # speed 0
            except Exception:
                pass
            self.color_combo.configure(state="disabled")
        else:
            try:
                self.rb_scroll_children[0].configure(state="normal")
            except Exception:
                pass
            self.color_combo.configure(state="readonly")
        self.update_counter()

    # ---------- actions ----------
    def action_send_text(self):
        if self.lock_mode not in (None, "text"):
            messagebox.showinfo("Info", "Active timer. Press Clear to unlock."); return
        if self.lock_mode is None:
            self.set_mode("text")

        text = self.get_text()
        if not text.strip():
            messagebox.showwarning("Warning", "Text field is empty"); return

        self.stop_scroll()

        if self.rainbow_var.get():
            first_color = self.next_rainbow_color()
            self.scroll_speed_var.set("1")
            self.start_scroll(text, color_override=first_color, rainbow_cycle=True)
            return

        if self.scroll_speed_var.get() != "0":
            self.start_scroll(text)
            return
        self._send_plain(text)

    def action_clear_line(self):
        self.stop_scroll()
        self.stop_timer_job()
        self.timer_mode = None
        self.timer_start_ts = None
        self.timer_down_end_ts = None
        self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), ""))
        self.set_mode(None)

    def action_timer_up(self):
        if self.lock_mode not in (None, "up"):
            messagebox.showinfo("Info", "Another feature is active. Press Clear first."); return
        self.set_mode("up")
        self.stop_timer_job()
        self.timer_mode = 'up'
        self.timer_start_ts = time.time()
        self.tick_timer_up()

    def action_timer_down(self):
        if self.lock_mode not in (None, "down"):
            messagebox.showinfo("Info", "Another feature is active. Press Clear first."); return
        self.set_mode("down")
        self.stop_timer_job()
        mm = int(self.down_mm_var.get() or 0)
        ss = int(self.down_ss_var.get() or 0)
        fmt = f"{mm:02d}:{ss:02d}"
        total = mm * 60 + ss
        payload = self.wrap_color(self.cmd_rt(2, fmt), COLOR_MAP[self.down_color_var.get()])
        self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), payload))
        self.timer_mode = 'down'
        self.timer_start_ts = time.time()
        self.timer_down_end_ts = self.timer_start_ts + total
        if total > 0:
            self.timer_job = self.after(total * 1000, self.on_countdown_finished)

    def action_timer_stop(self):
        self.stop_timer_job()
        if not self.timer_mode and self.lock_mode not in ("up", "down"):
            return
        now = time.time()
        if self.timer_mode == 'up' and self.timer_start_ts is not None:
            elapsed = max(0.0, now - self.timer_start_ts)
            mm = int(elapsed // 60)
            ss_full = elapsed % 60
            ss = int(ss_full)
            cc = int((ss_full - ss) * 100)
            txt = f"{ss:02d}.{cc:02d}" if mm == 0 else f"{mm:02d}:{ss:02d}.{cc:02d}"
            color = COLOR_MAP[self.up_color_var.get()]
        else:
            remain = max(0.0, (self.timer_down_end_ts or now) - now)
            mm = int(remain // 60)
            ss = int(remain % 60)
            txt = f"{mm:02d}:{ss:02d}"
            color = COLOR_MAP[self.down_color_var.get()]
        payload = self.wrap_color(txt, color)
        self.send_bytes(self.build_frame(self.line_var.get(), self.brightness_var.get(), payload))

    # ---------- text helpers ----------
    def current_overhead(self) -> int:
        return len("^cs 10^") + len("^cs 0^") if self.rainbow_var.get() else 0

    def enforce_limit(self):
        allowed = max(0, 64 - self.current_overhead())
        raw = self.text_widget.get("1.0", "end-1c")
        if len(raw) > allowed:
            self.text_widget.delete("1.0", "end")
            self.text_widget.insert("1.0", raw[:allowed])

    def get_text(self) -> str:
        return self.text_widget.get("1.0", "end-1c")

    def update_counter(self, *_):
        allowed = max(0, 64 - self.current_overhead())
        length = len(self.get_text())
        left = allowed - length
        self.counter_var.set(f"{left} left")
        self.counter_label.configure(foreground="#ef4444" if left < 0 else self.subfg)

    def on_text_change(self, *_):
        self.enforce_limit()
        self.update_counter()

    # countdown after-text limiter
    def on_after_text_change(self, *_):
        s = self.down_finish_text_var.get()
        if len(s) > 30:
            self.down_finish_text_var.set(s[:30])
            s = s[:30]
        self.after_counter_var.set(f"{len(s)}/30")

    # ---------- UI ----------
    def build_ui(self):
        header_font = ("Helvetica", 18, "bold")

        root = ttk.Frame(self, padding=14, style="TFrame")
        root.pack(fill=tk.BOTH, expand=True)

        # port
        row = ttk.Frame(root, style="TFrame"); row.pack(fill=tk.X, pady=6)
        ttk.Label(row, text="Port", style="TLabel").pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value="")
        ttk.Entry(row, textvariable=self.port_var, width=34).pack(side=tk.LEFT, padx=8)
        self.btn_connect = RoundButton(row, text="Connect", command=self.open_serial,
                                       bg=GREEN_BG, hover=GREEN_HOVER, active=GREEN_ACTIVE, fg="#000000",
                                       ambient=self.bg); self.btn_connect.pack(side=tk.LEFT, padx=6)
        self.btn_disconnect = RoundButton(row, text="Disconnect", command=self.close_serial,
                                          bg=RED_BG, hover=RED_HOVER, active=RED_ACTIVE, fg="#000000",
                                          ambient=self.bg); self.btn_disconnect.pack(side=tk.LEFT, padx=6)
        self.btn_disconnect.set_enabled(False)
        RoundButton(row, text="Scan", command=self.scan_ports,
                    bg=GRAY_BG, hover=GRAY_HOVER, active=GRAY_ACTIVE, fg="#000000",
                    ambient=self.bg).pack(side=tk.LEFT, padx=6)

        # line / brightness / color
        row2 = ttk.Frame(root, style="TFrame"); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Line", style="TLabel").pack(side=tk.LEFT)
        self.line_var = tk.StringVar(value="7")
        line_combo = ttk.Combobox(row2, textvariable=self.line_var, values=LINE_CHOICES, width=5, state="readonly")
        line_combo.pack(side=tk.LEFT, padx=6); self.style_dark_combobox(line_combo)

        ttk.Label(row2, text="Brightness", style="TLabel").pack(side=tk.LEFT, padx=(12,0))
        self.brightness_var = tk.StringVar(value="1")
        for v in ["1","2","3"]:
            ttk.Radiobutton(row2, text=v, value=v, variable=self.brightness_var, style="TRadiobutton").pack(side=tk.LEFT)

        ttk.Label(row2, text="Text color", style="TLabel").pack(side=tk.LEFT, padx=(12,0))
        self.text_color_var = tk.StringVar(value="Default")
        self.color_combo = ttk.Combobox(row2, textvariable=self.text_color_var, values=list(COLOR_MAP.keys()), width=14, state="readonly")
        self.color_combo.pack(side=tk.LEFT, padx=6); self.style_dark_combobox(self.color_combo)
        self.color_combo.bind("<<ComboboxSelected>>", lambda e: (self.update_counter(),))

        # nagłówek Text
        ttk.Label(root, text="Text to display", style="TLabel", font=header_font).pack(pady=(10, 2), anchor="center")

        # pole tekstowe
        text_row = ttk.Frame(root, style="TFrame"); text_row.pack(fill=tk.X)
        self.text_widget = tk.Text(text_row, height=2, wrap="none", bg="#111111", fg=self.fg,
                                   insertbackground=self.fg, relief="flat", font=("Helvetica", 20))
        self.text_widget.pack(fill=tk.X)
        self.text_widget.bind("<KeyRelease>", self.on_text_change)
        self.text_widget.bind("<<Paste>>", self.on_text_change)

        # licznik znaków
        counter_row = ttk.Frame(root, style="TFrame"); counter_row.pack(fill=tk.X, pady=(4,6))
        self.counter_var = tk.StringVar(value="64 left")
        self.counter_label = ttk.Label(counter_row, textvariable=self.counter_var, style="TLabel")
        self.counter_label.pack(side=tk.RIGHT)

        # SEND full width
        send_full = ttk.Frame(root, style="TFrame"); send_full.pack(fill=tk.X, pady=(6, 6))
        self.btn_send = RoundButton(send_full, text="Send", command=self.action_send_text,
                                    bg=GREEN_BG, hover=GREEN_HOVER, active=GREEN_ACTIVE, fg="#000000",
                                    ambient=self.bg)
        self.btn_send.pack(side=tk.TOP, anchor="center", fill=tk.X, expand=True)
        self.btn_send.stretch_fraction(send_full, 1.0)

        # scroll + rainbow
        srow = ttk.Frame(root, style="TFrame"); srow.pack(fill=tk.X, pady=(0,10))
        left = ttk.Frame(srow, style="TFrame"); left.pack(side=tk.LEFT)
        ttk.Label(left, text="Scroll speed", style="TLabel").pack(side=tk.LEFT, padx=(0,6))
        self.scroll_speed_var = tk.StringVar(value="0")
        rb = ttk.Frame(left, style="TFrame"); rb.pack(side=tk.LEFT)
        self.rb_scroll_children = []
        for v in ["0","1","2","3"]:
            r = ttk.Radiobutton(rb, text=v, value=v, variable=self.scroll_speed_var, style="TRadiobutton")
            r.pack(side=tk.LEFT, padx=4); self.rb_scroll_children.append(r)
        tk.Checkbutton(srow, text="RAINBOW", variable=self.rainbow_var,
                       onvalue=True, offvalue=False, command=self.on_toggle_rainbow,
                       bg=self.bg, fg=self.fg, activebackground=self.bg, activeforeground=self.fg,
                       selectcolor=self.bg, highlightthickness=0, bd=0).pack(side=tk.RIGHT)

        # nagłówek Timer
        ttk.Label(root, text="Timer", style="TLabel", font=header_font).pack(pady=(6, 4), anchor="center")

        # cały Timer na tle aplikacji (bez jasnego panelu)
        timer = ttk.Frame(root, style="TFrame"); timer.pack(fill=tk.X, pady=0)

        # up
        up = ttk.Frame(timer, style="TFrame"); up.pack(fill=tk.X, pady=6)
        ttk.Label(up, text="Count up", style="TLabel").pack(side=tk.LEFT)
        ttk.Label(up, text="Color", style="TLabel").pack(side=tk.LEFT, padx=(12,4))
        self.up_color_var = tk.StringVar(value="Green")
        up_combo = ttk.Combobox(up, textvariable=self.up_color_var, values=list(COLOR_MAP.keys()), width=12, state="readonly")
        up_combo.pack(side=tk.LEFT); self.style_dark_combobox(up_combo)
        self.btn_up_start = RoundButton(up, text="Start", command=self.action_timer_up,
                                        bg=GREEN_BG, hover=GREEN_HOVER, active=GREEN_ACTIVE, fg="#000000",
                                        ambient=self.bg); self.btn_up_start.pack(side=tk.LEFT, padx=12)
        self.btn_up_stop = RoundButton(up, text="Stop", command=self.action_timer_stop,
                                       bg=RED_BG, hover=RED_HOVER, active=RED_ACTIVE, fg="#000000",
                                       ambient=self.bg); self.btn_up_stop.pack(side=tk.LEFT, padx=8)

        # down
        down = ttk.Frame(timer, style="TFrame"); down.pack(fill=tk.X, pady=6)
        ttk.Label(down, text="Count down", style="TLabel").pack(side=tk.LEFT)
        self.down_mm_var = tk.StringVar(value="10"); self.down_ss_var = tk.StringVar(value="00")
        ttk.Label(down, text="mm", style="TLabel").pack(side=tk.LEFT, padx=(8,0))
        ttk.Entry(down, textvariable=self.down_mm_var, width=4).pack(side=tk.LEFT)
        ttk.Label(down, text="ss", style="TLabel").pack(side=tk.LEFT, padx=(8,0))
        ttk.Entry(down, textvariable=self.down_ss_var, width=4).pack(side=tk.LEFT)
        ttk.Label(down, text="Color", style="TLabel").pack(side=tk.LEFT, padx=(12,4))
        self.down_color_var = tk.StringVar(value="Default")
        down_combo = ttk.Combobox(down, textvariable=self.down_color_var, values=list(COLOR_MAP.keys()), width=12, state="readonly")
        down_combo.pack(side=tk.LEFT); self.style_dark_combobox(down_combo)
        self.btn_down_start = RoundButton(down, text="Start", command=self.action_timer_down,
                                          bg=GREEN_BG, hover=GREEN_HOVER, active=GREEN_ACTIVE, fg="#000000",
                                          ambient=self.bg); self.btn_down_start.pack(side=tk.LEFT, padx=12)
        self.btn_down_stop = RoundButton(down, text="Stop", command=self.action_timer_stop,
                                         bg=RED_BG, hover=RED_HOVER, active=RED_ACTIVE, fg="#000000",
                                         ambient=self.bg); self.btn_down_stop.pack(side=tk.LEFT, padx=8)

        # after text + duration + flash
        down2 = ttk.Frame(timer, style="TFrame"); down2.pack(fill=tk.X, pady=6)
        ttk.Label(down2, text="After text", style="TLabel").pack(side=tk.LEFT)
        self.down_finish_text_var = tk.StringVar(value="")
        entry_after = ttk.Entry(down2, textvariable=self.down_finish_text_var, width=30)
        entry_after.pack(side=tk.LEFT, padx=(6,6))
        self.after_counter_var = tk.StringVar(value="0/30")
        ttk.Label(down2, textvariable=self.after_counter_var, style="TLabel").pack(side=tk.LEFT, padx=(0,12))
        self.down_finish_text_var.trace_add("write", self.on_after_text_change)

        ttk.Label(down2, text="Show (s)", style="TLabel").pack(side=tk.LEFT)
        self.down_finish_secs_var = tk.StringVar(value="5")
        tk.Spinbox(down2, from_=1, to=180, textvariable=self.down_finish_secs_var,
                   width=4, bg="#111111", fg=self.fg, insertbackground=self.fg,
                   relief="flat", highlightthickness=0).pack(side=tk.LEFT, padx=(6,12))

        # nowy przełącznik Flash
        self.down_flash_var = tk.BooleanVar(value=False)
        tk.Checkbutton(down2, text="Flash", variable=self.down_flash_var,
                       onvalue=True, offvalue=False,
                       bg=self.bg, fg=self.fg, activebackground=self.bg, activeforeground=self.fg,
                       selectcolor=self.bg, highlightthickness=0, bd=0).pack(side=tk.LEFT)

        # wspólny CLEAR
        bottom = ttk.Frame(root, style="TFrame"); bottom.pack(fill=tk.X, pady=(10, 6))
        self.btn_clear_bottom = RoundButton(bottom, text="Clear", command=self.action_clear_line,
                                            bg=BLUE_BG, hover=BLUE_HOVER, active=BLUE_ACTIVE, fg="#000000",
                                            ambient=self.bg)
        self.btn_clear_bottom.pack(fill=tk.X, expand=True)
        self.btn_clear_bottom.stretch_fraction(bottom, 1.0)

        # init
        self.after(50, self.update_counter)
        self.on_after_text_change()

    # ---------- scan ports ----------
    def scan_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            messagebox.showinfo("Ports", "No ports found"); return
        dlg = tk.Toplevel(self); dlg.title("Select port"); dlg.configure(bg=self.bg); dlg.geometry("360x280")
        lb = tk.Listbox(dlg, bg="#111111", fg=self.fg, selectbackground="#374151")
        for p in ports: lb.insert(tk.END, p)
        lb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        def choose():
            sel = lb.curselection()
            if sel: self.port_var.set(lb.get(sel[0]))
            dlg.destroy()
        RoundButton(dlg, text="OK", command=choose, bg=GREEN_BG, hover=GREEN_HOVER, active=GREEN_ACTIVE,
                    fg="#000000", ambient=self.bg).pack(pady=6)

if __name__ == "__main__":
    try:
        app = MLEDTerminal()
        app.mainloop()
    except KeyboardInterrupt:
        sys.exit(0)
