"""
Orik Launcher — Interfaz gráfica de control.
Coloca este archivo en la misma carpeta que app3test.py y ejecuta:
    python orik_launcher.py
Requiere: pip install psutil pillow
"""

import json
import os
import re
import sys
import queue
import signal
import socket
import subprocess
import threading
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import webbrowser
from datetime import datetime
from tkinter import font as tkfont

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Cuando el launcher corre como .exe (PyInstaller), __file__ apunta dentro del
# directorio temporal de extracción.  Los archivos de datos (config, memoria,
# icono) deben vivir junto al .exe real, que está en sys.executable.
if getattr(sys, "frozen", False):
    # Estamos dentro de un ejecutable PyInstaller
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(SCRIPT_DIR, "orik_config.json")
ICO_PATH    = os.path.join(SCRIPT_DIR, "icono.ico")

DEFAULT_CFG = {
    "theme":           "light",
    "port":            5000,
    "app_file":        "app3test.py",
    "model":           "gemma4:e2b",
    "autoscroll":      True,
    "font_size":       9,
    "start_minimized": False,
    "notify_crash":    True,
    "max_log_lines":   2000,
}

THEMES = {
    "light": {
        "BG":           "#f5f0e8",
        "SURFACE":      "#faf7f2",
        "SURFACE2":     "#f0ece3",
        "BORDER":       "#e8e1d5",
        "TEXT":         "#1a1a1a",
        "TEXT_MUTED":   "#6b6860",
        "ACCENT":       "#2563eb",
        "ACCENT_LIGHT": "#60a5fa",
        "ACCENT_BG":    "#eff6ff",
        "GREEN":        "#16a34a",
        "GREEN_BG":     "#f0fdf4",
        "YELLOW":       "#b45309",
        "RED":          "#dc2626",
        "RED_BG":       "#fee2e2",
        "LOG_BG":       "#1e1b16",
        "LOG_TEXT":     "#e8e1d5",
        "LOG_MUTED":    "#8a8070",
        "HDR_BG":       "#faf7f2",
        "HDR_LOGO":     "#1d4ed8",
    },
    "dark": {
        "BG":           "#0f1117",
        "SURFACE":      "#1a1d27",
        "SURFACE2":     "#22263a",
        "BORDER":       "#2e3348",
        "TEXT":         "#e8eaf6",
        "TEXT_MUTED":   "#7b82a8",
        "ACCENT":       "#4f8ef7",
        "ACCENT_LIGHT": "#93c5fd",
        "ACCENT_BG":    "#1e2a4a",
        "GREEN":        "#22c55e",
        "GREEN_BG":     "#0f2a1a",
        "YELLOW":       "#f59e0b",
        "RED":          "#f87171",
        "RED_BG":       "#2a1010",
        "LOG_BG":       "#080a0f",
        "LOG_TEXT":     "#c9d1e8",
        "LOG_MUTED":    "#4a5270",
        "HDR_BG":       "#13161f",
        "HDR_LOGO":     "#1d4ed8",
    },
}

_hostname_cache: dict = {}
_hostname_lock  = threading.Lock()

def resolve_hostname(ip: str) -> str:
    with _hostname_lock:
        if ip in _hostname_cache:
            return _hostname_cache[ip]
    def _resolve():
        try:
            host = socket.gethostbyaddr(ip)[0]
        except Exception:
            host = ip
        with _hostname_lock:
            _hostname_cache[ip] = host
    threading.Thread(target=_resolve, daemon=True).start()
    return "..."


class OrikLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            from ctypes import windll
            try:
                windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        self._cfg = self._load_config()
        self._t   = THEMES[self._cfg["theme"]]

        self.title("Orik - Panel de control")
        self.configure(bg=self._t["BG"])
        self.geometry("1100x700")
        self.minsize(860, 540)

        try:
            if os.path.exists(ICO_PATH):
                self.iconbitmap(ICO_PATH)
        except Exception:
            pass

        self._process        = None
        self._log_queue      = queue.Queue()
        self._running        = False
        self._start_time     = None
        self._logo_img       = None
        self._autoscroll     = tk.BooleanVar(value=self._cfg["autoscroll"])
        self._conn_history   = {}
        self._req_count      = {}
        self._log_line_count = 0
        self._log_buffer     = []

        self._build_fonts()
        self._build_ui()
        self._poll_logs()
        self._poll_stats()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if self._cfg.get("start_minimized"):
            self.after(100, self.iconify)

    # ── Config ────────────────────────────────────────────────
    def _load_config(self):
        cfg = dict(DEFAULT_CFG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        return cfg

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    # ── Fuentes ───────────────────────────────────────────────
    def _build_fonts(self):
        fs = self._cfg["font_size"]
        self._f_title  = tkfont.Font(family="Segoe UI", size=16, weight="bold")
        self._f_sub    = tkfont.Font(family="Segoe UI", size=9)
        self._f_label  = tkfont.Font(family="Segoe UI", size=9,  weight="bold")
        self._f_value  = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        self._f_small  = tkfont.Font(family="Segoe UI", size=8)
        self._f_mono   = tkfont.Font(family="Consolas",  size=fs)
        self._f_btn    = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._f_badge  = tkfont.Font(family="Segoe UI", size=8,  weight="bold")
        self._f_conn_b = tkfont.Font(family="Segoe UI", size=8,  weight="bold")

    # ── UI principal ──────────────────────────────────────────
    def _build_ui(self):
        t = self._t
        self._build_header()
        tk.Frame(self, bg=t["BORDER"], height=1).pack(fill="x")

        self._tab_bar    = tk.Frame(self, bg=t["BG"])
        self._tab_bar.pack(fill="x", padx=18, pady=(10, 0))
        self._tab_frames = {}
        self._tab_btns   = {}

        tab_container = tk.Frame(self, bg=t["BG"])
        tab_container.pack(fill="both", expand=True, padx=18, pady=(6, 14))

        for key, label in [("panel", "  Panel"), ("config", "  Configuracion")]:
            f = tk.Frame(tab_container, bg=t["BG"])
            self._tab_frames[key] = f
            btn = tk.Button(
                self._tab_bar, text=label,
                font=self._f_badge, relief="flat", cursor="hand2",
                padx=14, pady=5, bd=0,
                command=lambda k=key: self._switch_tab(k))
            btn.pack(side="left", padx=(0, 2))
            self._tab_btns[key] = btn

        self._build_panel_tab(self._tab_frames["panel"])
        self._build_config_tab(self._tab_frames["config"])
        self._switch_tab("panel")

    def _switch_tab(self, key):
        t = self._t
        for f in self._tab_frames.values():
            f.pack_forget()
        self._tab_frames[key].pack(fill="both", expand=True)
        for k, btn in self._tab_btns.items():
            if k == key:
                btn.config(bg=t["SURFACE"], fg=t["ACCENT"],
                           highlightthickness=1, highlightbackground=t["BORDER"])
            else:
                btn.config(bg=t["BG"], fg=t["TEXT_MUTED"],
                           highlightthickness=0)

    # ── Header ────────────────────────────────────────────────
    def _build_header(self):
        t   = self._t
        hdr = tk.Frame(self, bg=t["HDR_BG"], height=72)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        logo_box = tk.Frame(hdr, bg=t["HDR_LOGO"], width=48, height=48)
        logo_box.pack(side="left", padx=(22, 12), pady=12)
        logo_box.pack_propagate(False)

        logo_loaded = False
        if os.path.exists(ICO_PATH):
            try:
                from PIL import Image, ImageTk
                pil_img = Image.open(ICO_PATH).convert("RGBA")
                pil_img = pil_img.resize((40, 40), Image.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(pil_img)
                tk.Label(logo_box, image=self._logo_img, bg=t["HDR_LOGO"],
                         borderwidth=0, highlightthickness=0).place(
                    relx=.5, rely=.5, anchor="center")
                logo_loaded = True
            except Exception:
                pass
            if not logo_loaded:
                try:
                    img = tk.PhotoImage(file=ICO_PATH)
                    iw, ih = img.width(), img.height()
                    factor = max(iw // 40, ih // 40, 1)
                    if factor > 1:
                        img = img.subsample(factor, factor)
                    self._logo_img = img
                    tk.Label(logo_box, image=self._logo_img, bg=t["HDR_LOGO"],
                             borderwidth=0, highlightthickness=0).place(
                        relx=.5, rely=.5, anchor="center")
                    logo_loaded = True
                except Exception:
                    pass
        if not logo_loaded:
            tk.Label(logo_box, text="AI", font=tkfont.Font(family="Segoe UI", size=14, weight="bold"),
                     bg=t["HDR_LOGO"], fg="white").place(relx=.5, rely=.5, anchor="center")

        info = tk.Frame(hdr, bg=t["HDR_BG"])
        info.pack(side="left", pady=12)
        tk.Label(info, text="Orik", font=self._f_title,
                 bg=t["HDR_BG"], fg=t["TEXT"]).pack(anchor="w")
        tk.Label(info, text="Asistente IA local  Panel de control",
                 font=self._f_sub, bg=t["HDR_BG"], fg=t["TEXT_MUTED"]).pack(anchor="w")

        right = tk.Frame(hdr, bg=t["HDR_BG"])
        right.pack(side="right", padx=22)

        self._url_lbl = tk.Label(
            right, text=f"http://localhost:{self._cfg['port']}",
            font=tkfont.Font(family="Segoe UI", size=9, underline=True),
            bg=t["HDR_BG"], fg=t["ACCENT"], cursor="hand2")
        self._url_lbl.bind("<Button-1>", lambda e: self._open_browser())

        badge = tk.Frame(right, bg=t["HDR_BG"])
        badge.pack(anchor="e")
        self._dot = tk.Label(badge, text="*", font=("Segoe UI", 13),
                             bg=t["HDR_BG"], fg=t["RED"])
        self._dot.pack(side="left")
        self._status_lbl = tk.Label(badge, text="Detenido",
                                    font=self._f_sub,
                                    bg=t["HDR_BG"], fg=t["TEXT_MUTED"])
        self._status_lbl.pack(side="left", padx=(4, 0))

    # ── Pestaña Panel ─────────────────────────────────────────
    def _build_panel_tab(self, parent):
        left = tk.Frame(parent, bg=self._t["BG"], width=300)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        right = tk.Frame(parent, bg=self._t["BG"])
        right.pack(side="left", fill="both", expand=True)
        self._build_left(left)
        self._build_right(right)

    def _card(self, parent, title=None, pady_inner=(12, 12)):
        t     = self._t
        outer = tk.Frame(parent, bg=t["BG"])
        outer.pack(fill="x", pady=(0, 10))
        card  = tk.Frame(outer, bg=t["SURFACE"],
                         highlightthickness=1, highlightbackground=t["BORDER"])
        card.pack(fill="x")
        inner = tk.Frame(card, bg=t["SURFACE"])
        inner.pack(fill="x", padx=14, pady=pady_inner)
        if title:
            tk.Label(inner, text=title, font=self._f_badge,
                     bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(anchor="w", pady=(0, 8))
        return inner

    def _build_left(self, parent):
        t = self._t

        btn_card = self._card(parent, pady_inner=(14, 14))

        self._btn_start = tk.Button(
            btn_card, text="> Arrancar servidor",
            font=self._f_btn, relief="flat", cursor="hand2",
            bg=t["ACCENT"], fg="white", activebackground="#1d4ed8",
            padx=0, pady=9, bd=0, command=self._start_server)
        self._btn_start.pack(fill="x", pady=(0, 6))

        self._btn_restart = tk.Button(
            btn_card, text="Reiniciar servidor",
            font=self._f_btn, relief="flat", cursor="hand2",
            bg=t["SURFACE2"], fg=t["TEXT"], activebackground=t["BORDER"],
            padx=0, pady=9, bd=0, state="disabled",
            command=self._restart_server)
        self._btn_restart.pack(fill="x", pady=(0, 6))

        self._btn_stop = tk.Button(
            btn_card, text="Detener servidor",
            font=self._f_btn, relief="flat", cursor="hand2",
            bg=t["RED_BG"], fg=t["RED"], activebackground="#fecaca",
            padx=0, pady=9, bd=0, state="disabled",
            command=self._stop_server)
        self._btn_stop.pack(fill="x", pady=(0, 6))

        self._btn_open = tk.Button(
            btn_card, text="Abrir en navegador",
            font=self._f_btn, relief="flat", cursor="hand2",
            bg=t["ACCENT_BG"], fg=t["ACCENT"], activebackground="#dbeafe",
            padx=0, pady=9, bd=0, state="disabled",
            command=self._open_browser)
        self._btn_open.pack(fill="x", pady=(0, 6))

        self._btn_folder = tk.Button(
            btn_card, text="Abrir carpeta del proyecto",
            font=self._f_btn, relief="flat", cursor="hand2",
            bg=t["SURFACE2"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
            padx=0, pady=9, bd=0, command=self._open_folder)
        self._btn_folder.pack(fill="x")

        # Info servidor
        info_card = self._card(parent, title="SERVIDOR", pady_inner=(12, 14))
        self._uptime_var = tk.StringVar(value="--")
        self._model_var  = tk.StringVar(value=self._cfg["model"])
        self._port_var   = tk.StringVar(value=str(self._cfg["port"]))
        for label, var in [("Tiempo activo", self._uptime_var),
                            ("Modelo",        self._model_var),
                            ("Puerto",        self._port_var)]:
            row = tk.Frame(info_card, bg=t["SURFACE"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=self._f_sub,
                     bg=t["SURFACE"], fg=t["TEXT_MUTED"],
                     width=13, anchor="w").pack(side="left")
            tk.Label(row, textvariable=var, font=self._f_sub,
                     bg=t["SURFACE"], fg=t["TEXT"], anchor="w").pack(side="left")

        # Metricas
        metrics_card = self._card(parent, title="SISTEMA", pady_inner=(12, 14))
        self._cpu_var = tk.StringVar(value="-- %")
        self._ram_var = tk.StringVar(value="-- %")
        self._ram_gb  = tk.StringVar(value="")

        for label, var, sub_var in [("CPU", self._cpu_var, None),
                                     ("RAM", self._ram_var, self._ram_gb)]:
            row = tk.Frame(metrics_card, bg=t["SURFACE"])
            row.pack(fill="x", pady=(0, 2))
            tk.Label(row, text=label, font=self._f_label,
                     bg=t["SURFACE"], fg=t["TEXT_MUTED"],
                     width=5, anchor="w").pack(side="left")
            vf = tk.Frame(row, bg=t["SURFACE"])
            vf.pack(side="left")
            tk.Label(vf, textvariable=var, font=self._f_value,
                     bg=t["SURFACE"], fg=t["ACCENT"]).pack(side="left")
            if sub_var:
                tk.Label(vf, textvariable=sub_var, font=self._f_sub,
                         bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(side="left", padx=(6, 0))
            bar_bg = tk.Frame(metrics_card, bg=t["BORDER"], height=5)
            bar_bg.pack(fill="x", pady=(0, 8))
            bar_bg.pack_propagate(False)
            bar_fill = tk.Frame(bar_bg, bg=t["ACCENT"], height=5)
            bar_fill.place(x=0, y=0, relheight=1, relwidth=0)
            if label == "CPU":
                self._cpu_bar    = bar_fill
                self._cpu_bar_bg = bar_bg
            else:
                self._ram_bar    = bar_fill
                self._ram_bar_bg = bar_bg

        if not HAS_PSUTIL:
            tk.Label(metrics_card, text="pip install psutil para ver metricas",
                     font=self._f_small, bg=t["SURFACE"], fg=t["YELLOW"],
                     justify="left").pack(anchor="w")

        self._build_connections_panel(parent)

    def _build_connections_panel(self, parent):
        t     = self._t
        outer = tk.Frame(parent, bg=t["BG"])
        outer.pack(fill="x", pady=(0, 10))
        card  = tk.Frame(outer, bg=t["SURFACE"],
                         highlightthickness=1, highlightbackground=t["BORDER"])
        card.pack(fill="x")

        hdr = tk.Frame(card, bg=t["SURFACE"])
        hdr.pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(hdr, text="CONEXIONES", font=self._f_badge,
                 bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(side="left")
        self._conn_badge = tk.Label(hdr, text="0", font=self._f_badge,
                                    bg=t["BORDER"], fg=t["TEXT_MUTED"], padx=6, pady=1)
        self._conn_badge.pack(side="left", padx=(6, 0))
        tk.Button(hdr, text="Limpiar historial", font=self._f_small,
                  relief="flat", cursor="hand2",
                  bg=t["SURFACE"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
                  padx=6, pady=1, bd=0,
                  command=self._clear_conn_history).pack(side="right")

        cols = tk.Frame(card, bg=t["SURFACE2"])
        cols.pack(fill="x", padx=14, pady=(6, 0))
        for txt, w, anc in [("IP / Host", 0, "w"), ("Req.", 48, "e"), ("Ultima vez", 66, "e")]:
            kw = {"width": w} if w else {}
            tk.Label(cols, text=txt, font=self._f_badge,
                     bg=t["SURFACE2"], fg=t["TEXT_MUTED"], anchor=anc, **kw).pack(
                side="left", padx=(0, 4), pady=3,
                expand=(w == 0), fill="x" if w == 0 else None)

        list_f = tk.Frame(card, bg=t["SURFACE"])
        list_f.pack(fill="x", padx=14, pady=(2, 10))
        canvas = tk.Canvas(list_f, bg=t["SURFACE"], highlightthickness=0, height=112)
        vsb    = tk.Scrollbar(list_f, orient="vertical", command=canvas.yview,
                              bg=t["SURFACE"], troughcolor=t["SURFACE"],
                              highlightthickness=0, bd=0, relief="flat")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._conn_inner  = tk.Frame(canvas, bg=t["SURFACE"])
        self._conn_window = canvas.create_window((0, 0), window=self._conn_inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._conn_window, width=e.width))
        self._conn_inner.bind("<Configure>",
                              lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        self._conn_canvas = canvas
        tk.Label(self._conn_inner, text="Sin conexiones aun",
                 font=self._f_small, bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(pady=12)

    def _build_right(self, parent):
        t = self._t

        log_hdr = tk.Frame(parent, bg=t["BG"])
        log_hdr.pack(fill="x", pady=(0, 6))
        tk.Label(log_hdr, text="LOGS DEL SERVIDOR",
                 font=self._f_badge, bg=t["BG"], fg=t["TEXT_MUTED"]).pack(side="left")

        tk.Button(log_hdr, text="Guardar log",
                  font=self._f_small, relief="flat", cursor="hand2",
                  bg=t["SURFACE"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
                  padx=8, pady=3, bd=0, command=self._save_logs).pack(side="right", padx=(4, 0))
        tk.Button(log_hdr, text="Limpiar",
                  font=self._f_small, relief="flat", cursor="hand2",
                  bg=t["SURFACE"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
                  padx=8, pady=3, bd=0, command=self._clear_logs).pack(side="right", padx=(4, 0))
        tk.Checkbutton(log_hdr, text="Auto-scroll", variable=self._autoscroll,
                       font=self._f_small, relief="flat", cursor="hand2",
                       bg=t["BG"], fg=t["TEXT_MUTED"], activebackground=t["BG"],
                       selectcolor=t["SURFACE"], bd=0).pack(side="right", padx=(0, 8))

        # Barra de filtro
        filter_frame = tk.Frame(parent, bg=t["SURFACE"],
                                highlightthickness=1, highlightbackground=t["BORDER"])
        filter_frame.pack(fill="x", pady=(0, 6))
        tk.Label(filter_frame, text="Filtrar:", font=self._f_small,
                 bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(side="left", padx=(8, 4))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._apply_log_filter())
        tk.Entry(filter_frame, textvariable=self._filter_var,
                 font=self._f_mono, relief="flat", bd=0,
                 bg=t["SURFACE"], fg=t["TEXT"],
                 insertbackground=t["TEXT"]).pack(side="left", fill="x", expand=True, pady=5)
        tk.Button(filter_frame, text="X", font=self._f_small, relief="flat", cursor="hand2",
                  bg=t["SURFACE"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
                  padx=6, bd=0, command=lambda: self._filter_var.set("")).pack(side="right")

        log_wrap = tk.Frame(parent, bg=t["SURFACE"],
                            highlightthickness=1, highlightbackground=t["BORDER"])
        log_wrap.pack(fill="both", expand=True)
        self._log = tk.Text(
            log_wrap, bg=t["LOG_BG"], fg=t["LOG_TEXT"],
            font=self._f_mono, relief="flat", bd=0,
            state="disabled", wrap="word",
            selectbackground="#3a3025",
            padx=14, pady=12, spacing1=3)
        scroll = tk.Scrollbar(log_wrap, command=self._log.yview,
                              bg=t["LOG_BG"], troughcolor=t["LOG_BG"],
                              highlightthickness=0, bd=0, relief="flat")
        self._log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        for c in [t["GREEN"], t["ACCENT_LIGHT"], "#d97706", "#f87171", t["LOG_TEXT"], t["LOG_MUTED"]]:
            self._log.tag_configure(c, foreground=c)
        self._log.tag_configure("ts", foreground="#5a5040")

    # ── Pestana Configuracion ─────────────────────────────────
    def _build_config_tab(self, parent):
        t = self._t

        canvas = tk.Canvas(parent, bg=t["BG"], highlightthickness=0)
        vsb    = tk.Scrollbar(parent, orient="vertical", command=canvas.yview,
                              bg=t["BG"], troughcolor=t["BG"],
                              highlightthickness=0, bd=0, relief="flat")
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=t["BG"])
        win   = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def section(title):
            f = tk.Frame(inner, bg=t["BG"])
            f.pack(fill="x", padx=24, pady=(16, 4))
            tk.Label(f, text=title, font=self._f_badge,
                     bg=t["BG"], fg=t["TEXT_MUTED"]).pack(anchor="w")
            tk.Frame(inner, bg=t["BORDER"], height=1).pack(fill="x", padx=24)

        def card_frame():
            outer = tk.Frame(inner, bg=t["BG"])
            outer.pack(fill="x", padx=24, pady=(4, 0))
            card  = tk.Frame(outer, bg=t["SURFACE"],
                             highlightthickness=1, highlightbackground=t["BORDER"])
            card.pack(fill="x")
            return card

        def row_entry(parent_f, label, var, width=18, tip=""):
            r = tk.Frame(parent_f, bg=t["SURFACE"])
            r.pack(fill="x", padx=14, pady=4)
            lf = tk.Frame(r, bg=t["SURFACE"], width=200)
            lf.pack(side="left")
            lf.pack_propagate(False)
            tk.Label(lf, text=label, font=self._f_sub,
                     bg=t["SURFACE"], fg=t["TEXT"], anchor="w").pack(anchor="w", pady=2)
            if tip:
                tk.Label(lf, text=tip, font=self._f_small,
                         bg=t["SURFACE"], fg=t["TEXT_MUTED"],
                         anchor="w", wraplength=180, justify="left").pack(anchor="w")
            tk.Entry(r, textvariable=var, font=self._f_sub, width=width,
                     relief="flat", bd=4,
                     bg=t["SURFACE2"], fg=t["TEXT"],
                     insertbackground=t["TEXT"]).pack(side="left", padx=(8, 0), pady=6)

        def row_check(parent_f, label, var, tip=""):
            r = tk.Frame(parent_f, bg=t["SURFACE"])
            r.pack(fill="x", padx=14, pady=2)
            tk.Checkbutton(r, text=label, variable=var,
                           font=self._f_sub, relief="flat",
                           bg=t["SURFACE"], fg=t["TEXT"],
                           activebackground=t["SURFACE"],
                           selectcolor=t["SURFACE2"],
                           cursor="hand2").pack(side="left", pady=4)
            if tip:
                tk.Label(r, text="  " + tip, font=self._f_small,
                         bg=t["SURFACE"], fg=t["TEXT_MUTED"]).pack(side="left")

        # Servidor
        section("SERVIDOR")
        srv = card_frame()
        self._cfg_port     = tk.StringVar(value=str(self._cfg["port"]))
        self._cfg_app_file = tk.StringVar(value=self._cfg["app_file"])
        self._cfg_model    = tk.StringVar(value=self._cfg["model"])
        row_entry(srv, "Puerto", self._cfg_port, width=8,
                  tip="Puerto donde escucha Flask (por defecto 5000)")
        row_entry(srv, "Archivo de la app", self._cfg_app_file, width=26,
                  tip="Script principal a lanzar")
        row_entry(srv, "Modelo IA", self._cfg_model, width=22,
                  tip="Nombre del modelo Ollama a usar")

        # Interfaz
        section("INTERFAZ")
        ui = card_frame()

        theme_row = tk.Frame(ui, bg=t["SURFACE"])
        theme_row.pack(fill="x", padx=14, pady=6)
        tk.Label(theme_row, text="Tema de color", font=self._f_sub,
                 bg=t["SURFACE"], fg=t["TEXT"], width=24, anchor="w").pack(side="left")
        self._cfg_theme = tk.StringVar(value=self._cfg["theme"])
        for val, lbl in [("light", "Claro"), ("dark", "Oscuro")]:
            tk.Radiobutton(theme_row, text=lbl, value=val,
                           variable=self._cfg_theme,
                           font=self._f_sub, relief="flat",
                           bg=t["SURFACE"], fg=t["TEXT"],
                           activebackground=t["SURFACE"],
                           selectcolor=t["SURFACE2"],
                           cursor="hand2").pack(side="left", padx=(0, 16))

        self._cfg_font_size = tk.StringVar(value=str(self._cfg["font_size"]))
        self._cfg_max_lines = tk.StringVar(value=str(self._cfg["max_log_lines"]))
        row_entry(ui, "Tamano fuente logs (pt)", self._cfg_font_size, width=6,
                  tip="Tamano en puntos para la fuente Consolas (6-24)")
        row_entry(ui, "Max. lineas de log", self._cfg_max_lines, width=8,
                  tip="Lineas acumuladas antes de truncar automaticamente")

        # Comportamiento
        section("COMPORTAMIENTO")
        beh = card_frame()
        self._cfg_autoscroll   = tk.BooleanVar(value=self._cfg["autoscroll"])
        self._cfg_start_min    = tk.BooleanVar(value=self._cfg["start_minimized"])
        self._cfg_notify_crash = tk.BooleanVar(value=self._cfg["notify_crash"])
        row_check(beh, "Auto-scroll en logs", self._cfg_autoscroll)
        row_check(beh, "Iniciar minimizado", self._cfg_start_min,
                  tip="La ventana arranca en la barra de tareas")
        row_check(beh, "Notificar si el servidor se cae", self._cfg_notify_crash,
                  tip="Muestra un dialogo de alerta")

        # Botones guardar
        save_row = tk.Frame(inner, bg=t["BG"])
        save_row.pack(fill="x", padx=24, pady=16)
        tk.Button(save_row, text="Guardar configuracion",
                  font=self._f_btn, relief="flat", cursor="hand2",
                  bg=t["ACCENT"], fg="white", activebackground="#1d4ed8",
                  padx=20, pady=9, bd=0,
                  command=self._apply_config).pack(side="left")
        tk.Button(save_row, text="Restablecer valores por defecto",
                  font=self._f_btn, relief="flat", cursor="hand2",
                  bg=t["SURFACE2"], fg=t["TEXT_MUTED"], activebackground=t["BORDER"],
                  padx=20, pady=9, bd=0,
                  command=self._reset_config).pack(side="left", padx=(10, 0))

        self._cfg_status_lbl = tk.Label(inner, text="", font=self._f_small,
                                        bg=t["BG"], fg=t["GREEN"])
        self._cfg_status_lbl.pack(anchor="w", padx=24)

    def _apply_config(self):
        try:
            port = int(self._cfg_port.get())
            assert 1 <= port <= 65535
        except Exception:
            mb.showerror("Error", "Puerto invalido (1-65535)")
            return
        try:
            fs = int(self._cfg_font_size.get())
            assert 6 <= fs <= 24
        except Exception:
            mb.showerror("Error", "Tamano de fuente invalido (6-24)")
            return
        try:
            ml = int(self._cfg_max_lines.get())
            assert ml >= 100
        except Exception:
            mb.showerror("Error", "Max. lineas debe ser >= 100")
            return

        prev_theme = self._cfg["theme"]
        self._cfg.update({
            "port":            port,
            "app_file":        self._cfg_app_file.get().strip(),
            "model":           self._cfg_model.get().strip(),
            "theme":           self._cfg_theme.get(),
            "font_size":       fs,
            "max_log_lines":   ml,
            "autoscroll":      self._cfg_autoscroll.get(),
            "start_minimized": self._cfg_start_min.get(),
            "notify_crash":    self._cfg_notify_crash.get(),
        })
        self._save_config()
        self._port_var.set(str(port))
        self._model_var.set(self._cfg["model"])
        self._url_lbl.config(text=f"http://localhost:{port}")
        self._autoscroll.set(self._cfg["autoscroll"])
        self._f_mono.config(size=fs)

        if self._cfg["theme"] != prev_theme:
            self._cfg_status_lbl.config(
                text="Guardado. Reinicia el launcher para aplicar el tema.",
                fg=self._t["YELLOW"])
        else:
            self._cfg_status_lbl.config(
                text="Configuracion guardada correctamente.", fg=self._t["GREEN"])
        self.after(4000, lambda: self._cfg_status_lbl.config(text=""))

    def _reset_config(self):
        if not mb.askyesno("Restablecer", "Restablecer todos los valores por defecto?"):
            return
        self._cfg = dict(DEFAULT_CFG)
        self._save_config()
        self._cfg_port.set(str(self._cfg["port"]))
        self._cfg_app_file.set(self._cfg["app_file"])
        self._cfg_model.set(self._cfg["model"])
        self._cfg_theme.set(self._cfg["theme"])
        self._cfg_font_size.set(str(self._cfg["font_size"]))
        self._cfg_max_lines.set(str(self._cfg["max_log_lines"]))
        self._cfg_autoscroll.set(self._cfg["autoscroll"])
        self._cfg_start_min.set(self._cfg["start_minimized"])
        self._cfg_notify_crash.set(self._cfg["notify_crash"])
        self._cfg_status_lbl.config(text="Valores restablecidos.", fg=self._t["TEXT_MUTED"])
        self.after(3000, lambda: self._cfg_status_lbl.config(text=""))

    # ── Servidor ──────────────────────────────────────────────
    def _port_in_use(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0


    def _find_python(self):
        """
        Devuelve la ruta al intérprete Python para arrancar app3test.py.
        Si no estamos en un exe (frozen), sys.executable ya es Python.
        Si estamos en un exe de PyInstaller, buscamos Python en el sistema.
        """
        if not getattr(sys, 'frozen', False):
            return sys.executable

        import shutil
        for candidate in ('python', 'python3', 'py'):
            path = shutil.which(candidate)
            if path:
                return path

        if os.name == 'nt':
            drives = ['C:', 'D:']
            for drive in drives:
                drive_root = drive + '\\'
                if os.path.exists(drive_root):
                    try:
                        for folder in os.listdir(drive_root):
                            if folder.lower().startswith('python'):
                                exe = os.path.join(drive_root, folder, 'python.exe')
                                if os.path.isfile(exe):
                                    return exe
                    except Exception:
                        pass
            py_launcher = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'py.exe')
            if os.path.isfile(py_launcher):
                return py_launcher
            try:
                import winreg
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for base in (r'SOFTWARE\Python\PythonCore',
                                 r'SOFTWARE\WOW6432Node\Python\PythonCore'):
                        try:
                            key = winreg.OpenKey(hive, base)
                            i = 0
                            while True:
                                try:
                                    ver = winreg.EnumKey(key, i)
                                    inst_key = winreg.OpenKey(key, ver + r'\InstallPath')
                                    install_path, _ = winreg.QueryValueEx(inst_key, '')
                                    exe = os.path.join(install_path, 'python.exe')
                                    if os.path.isfile(exe):
                                        return exe
                                    i += 1
                                except OSError:
                                    break
                        except OSError:
                            continue
            except Exception:
                pass
        return None

    def _start_server(self):
        if self._running:
            return
        port = self._cfg["port"]
        if self._port_in_use(port):
            if not mb.askyesno("Puerto ocupado",
                               f"El puerto {port} ya esta en uso.\nIntentar arrancar igualmente?"):
                return
        app_file = os.path.join(SCRIPT_DIR, self._cfg["app_file"])
        if not os.path.exists(app_file):
            self._append_log(f"No se encuentra {self._cfg['app_file']} en: {SCRIPT_DIR}", "#f87171")
            return
        self._append_log("Arrancando servidor Orik...", "#d97706")
        self._set_status("Iniciando...", self._t["YELLOW"])

        # Cuando corremos como .exe (PyInstaller), sys.executable apunta al
        # propio .exe, no a Python.  _find_python() localiza el intérprete real.
        python_exe = self._find_python()
        if python_exe is None:
            self._append_log(
                "No se encontró Python en el sistema. "
                "Instala Python y asegúrate de que esté en el PATH.", "#f87171")
            self._set_status("Error", self._t["RED"])
            return
        self._append_log(f"Usando Python: {python_exe}", self._t["LOG_MUTED"])

        try:
            self._process = subprocess.Popen(
                [python_exe, app_file],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                cwd=SCRIPT_DIR,
                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"})
        except Exception as e:
            self._append_log(f"Error al iniciar: {e}", "#f87171")
            return
        self._running    = True
        self._start_time = datetime.now()
        self._btn_start.config(state="disabled")
        self._btn_restart.config(state="normal")
        self._btn_stop.config(state="normal")
        self._btn_open.config(state="normal")
        self._url_lbl.pack(anchor="e", pady=(0, 2))
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self):
        try:
            for line in self._process.stdout:
                self._log_queue.put(line.rstrip("\n"))
        except Exception:
            pass
        finally:
            self._log_queue.put(None)

    def _stop_server(self, silent=False):
        if not self._running or not self._process:
            return
        if not silent:
            self._append_log("Deteniendo servidor...", "#d97706")
        try:
            if os.name == "nt":
                self._process.send_signal(signal.CTRL_C_EVENT)
            else:
                self._process.terminate()
            self._process.wait(timeout=5)
        except Exception:
            self._process.kill()
        self._running    = False
        self._process    = None
        self._start_time = None
        self._uptime_var.set("--")
        self._btn_start.config(state="normal")
        self._btn_restart.config(state="disabled")
        self._btn_stop.config(state="disabled")
        self._btn_open.config(state="disabled")
        self._url_lbl.pack_forget()
        self._set_status("Detenido", self._t["RED"])
        if not silent:
            self._append_log("Servidor detenido.", self._t["GREEN"])
        self._update_conn_table()

    def _restart_server(self):
        self._append_log("Reiniciando servidor...", "#d97706")
        self._stop_server(silent=True)
        self.after(800, self._start_server)

    def _open_browser(self):
        webbrowser.open(f"http://localhost:{self._cfg['port']}")

    def _open_folder(self):
        if os.name == "nt":
            os.startfile(SCRIPT_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", SCRIPT_DIR])
        else:
            subprocess.Popen(["xdg-open", SCRIPT_DIR])

    # ── Logs ──────────────────────────────────────────────────
    def _color_for_line(self, line):
        t = self._t
        if any(x in line for x in ["listo", "corriendo", "Running", "detenido"]):
            return t["GREEN"]
        if any(x in line for x in ["Arrancando", "Reiniciando", "Abriendo"]):
            return t["ACCENT_LIGHT"]
        if any(x in line for x in ["Deteniendo", "terminó"]):
            return "#d97706"
        if any(x in line for x in ["Error", "error", "ERROR", "Traceback", "No se"]):
            return "#f87171"
        if any(x in line for x in ["GET /", "POST /", "HTTP/", " 200 ", " 404 "]):
            return t["LOG_MUTED"]
        return t["LOG_TEXT"]

    def _append_log(self, line, color=None):
        ts    = datetime.now().strftime("%H:%M:%S")
        color = color or self._color_for_line(line)
        self._log_buffer.append((ts, line, color))
        self._log_line_count += 1

        max_lines = self._cfg.get("max_log_lines", 2000)
        if self._log_line_count > max_lines + 200:
            self._log_buffer = self._log_buffer[-max_lines:]
            self._log_line_count = max_lines
            self._redraw_log()
            return

        flt = self._filter_var.get().lower() if hasattr(self, "_filter_var") else ""
        if flt and flt not in line.lower():
            return

        self._log.config(state="normal")
        self._log.insert("end", f"[{ts}] ", "ts")
        self._log.insert("end", line + "\n", color)
        self._log.config(state="disabled")
        if self._autoscroll.get():
            self._log.see("end")

        self._parse_request_from_log(line)

    def _parse_request_from_log(self, line):
        m = re.match(r"(\d{1,3}(?:\.\d{1,3}){3})\s+-\s+-", line)
        if m:
            ip = m.group(1)
            self._req_count[ip] = self._req_count.get(ip, 0) + 1
            if ip in self._conn_history:
                self._conn_history[ip]["last_seen"] = datetime.now()
                self._conn_history[ip]["requests"]  = self._req_count[ip]

    def _apply_log_filter(self):
        self._redraw_log()

    def _redraw_log(self):
        flt = self._filter_var.get().lower() if hasattr(self, "_filter_var") else ""
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        for ts, line, color in self._log_buffer:
            if flt and flt not in line.lower():
                continue
            self._log.insert("end", f"[{ts}] ", "ts")
            self._log.insert("end", line + "\n", color)
        self._log.config(state="disabled")
        if self._autoscroll.get():
            self._log.see("end")

    def _clear_logs(self):
        self._log_buffer.clear()
        self._log_line_count = 0
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    def _save_logs(self):
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = fd.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"orik_log_{ts}.txt",
            filetypes=[("Archivo de texto", "*.txt"), ("Todos", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                for ts_s, line, _ in self._log_buffer:
                    f.write(f"[{ts_s}] {line}\n")
            self._append_log(f"Log guardado en: {path}", self._t["GREEN"])
        except Exception as e:
            self._append_log(f"No se pudo guardar: {e}", "#f87171")

    def _poll_logs(self):
        try:
            while True:
                line = self._log_queue.get_nowait()
                if line is None:
                    if self._running:
                        self._running    = False
                        self._start_time = None
                        self._uptime_var.set("--")
                        self._btn_start.config(state="normal")
                        self._btn_restart.config(state="disabled")
                        self._btn_stop.config(state="disabled")
                        self._btn_open.config(state="disabled")
                        self._url_lbl.pack_forget()
                        self._set_status("Detenido", self._t["RED"])
                        self._append_log("El proceso termino inesperadamente.", "#d97706")
                        self._update_conn_table()
                        if self._cfg.get("notify_crash"):
                            self.after(100, lambda: mb.showwarning(
                                "Orik - Caida del servidor",
                                "El servidor se ha detenido inesperadamente.\n"
                                "Revisa los logs para mas detalles."))
                else:
                    if any(x in line for x in ["Servidor corriendo", "Running on"]):
                        self._set_status("En ejecucion", self._t["GREEN"])
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(80, self._poll_logs)

    # ── Stats ─────────────────────────────────────────────────
    def _poll_stats(self):
        if HAS_PSUTIL:
            cpu = psutil.cpu_percent(interval=None)
            self._cpu_var.set(f"{cpu:.0f}%")
            self._update_bar(self._cpu_bar, self._cpu_bar_bg, cpu / 100)
            mem = psutil.virtual_memory()
            self._ram_var.set(f"{mem.percent:.0f}%")
            used_gb  = mem.used  / (1024 ** 3)
            total_gb = mem.total / (1024 ** 3)
            self._ram_gb.set(f"{used_gb:.1f} / {total_gb:.1f} GB")
            self._update_bar(self._ram_bar, self._ram_bar_bg, mem.percent / 100)
            if self._start_time:
                delta = datetime.now() - self._start_time
                h, r  = divmod(int(delta.total_seconds()), 3600)
                m, s  = divmod(r, 60)
                self._uptime_var.set(f"{h}h {m}m {s}s" if h else f"{m}m {s}s")
            self._refresh_connections()
        self.after(2000, self._poll_stats)

    def _update_bar(self, bar_fill, bar_bg, ratio):
        t = self._t
        bar_bg.update_idletasks()
        w = bar_bg.winfo_width()
        if w > 1:
            bar_fill.place(x=0, y=0, width=max(4, int(w * ratio)), relheight=1)
            bar_fill.config(bg=t["RED"] if ratio > .85
                            else t["YELLOW"] if ratio > .65 else t["ACCENT"])

    # ── Conexiones ────────────────────────────────────────────
    def _get_active_ips(self):
        if not HAS_PSUTIL or not self._running:
            return set()
        try:
            port  = self._cfg["port"]
            conns = psutil.net_connections(kind="tcp")
            return {c.raddr.ip for c in conns
                    if c.laddr and c.laddr.port == port
                    and c.status == "ESTABLISHED" and c.raddr}
        except Exception:
            return set()

    def _refresh_connections(self):
        active_ips = self._get_active_ips()
        now        = datetime.now()
        for ip in active_ips:
            if ip not in self._conn_history:
                self._conn_history[ip] = {
                    "first_seen": now, "last_seen": now,
                    "requests":   self._req_count.get(ip, 0),
                    "hostname":   resolve_hostname(ip),
                }
            else:
                self._conn_history[ip]["last_seen"] = now
                self._conn_history[ip]["requests"]  = self._req_count.get(ip, 0)
                with _hostname_lock:
                    cached = _hostname_cache.get(ip)
                if cached:
                    self._conn_history[ip]["hostname"] = cached
        self._update_conn_table()

    def _update_conn_table(self):
        t = self._t
        for w in self._conn_inner.winfo_children():
            w.destroy()

        if not self._conn_history:
            tk.Label(self._conn_inner, text="Sin conexiones aun",
                     font=self._f_small, bg=t["SURFACE"],
                     fg=t["TEXT_MUTED"]).pack(pady=12)
            self._conn_badge.config(text="0", bg=t["BORDER"], fg=t["TEXT_MUTED"])
            return

        now        = datetime.now()
        active_ips = self._get_active_ips()
        entries    = sorted(self._conn_history.items(),
                            key=lambda kv: (kv[0] not in active_ips,
                                            -(kv[1]["last_seen"].timestamp())))
        n_active = len(active_ips)
        self._conn_badge.config(
            text=str(n_active) if n_active else str(len(entries)),
            bg=t["GREEN"] if n_active else t["BORDER"],
            fg="white"    if n_active else t["TEXT_MUTED"])

        for idx, (ip, info) in enumerate(entries):
            is_active = ip in active_ips
            row_bg    = t["GREEN_BG"] if is_active else t["SURFACE"]
            row       = tk.Frame(self._conn_inner, bg=row_bg)
            row.pack(fill="x", pady=(1, 0))
            tk.Label(row, text="*", font=("Segoe UI", 7),
                     bg=row_bg,
                     fg=t["GREEN"] if is_active else t["BORDER"]).pack(side="left", padx=(2, 4))
            ip_f = tk.Frame(row, bg=row_bg)
            ip_f.pack(side="left", fill="x", expand=True)
            tk.Label(ip_f, text=ip, font=self._f_conn_b,
                     bg=row_bg, fg=t["TEXT"], anchor="w").pack(anchor="w")
            hostname = info.get("hostname", ip)
            if hostname and hostname != ip:
                tk.Label(ip_f, text=hostname, font=self._f_small,
                         bg=row_bg, fg=t["TEXT_MUTED"], anchor="w").pack(anchor="w")
            req = self._req_count.get(ip, info.get("requests", 0))
            tk.Label(row, text=str(req), font=self._f_conn_b,
                     bg=row_bg, fg=t["ACCENT"], width=4, anchor="e").pack(side="right", padx=(0, 2))
            delta    = now - info["last_seen"]
            secs     = delta.total_seconds()
            time_str = (f"{int(secs)}s"           if secs  <  60
                        else f"{int(secs//60)}m"   if secs < 3600
                        else info["last_seen"].strftime("%H:%M"))
            tk.Label(row, text=time_str, font=self._f_small,
                     bg=row_bg, fg=t["TEXT_MUTED"],
                     width=6, anchor="e").pack(side="right", padx=(0, 4))
            if idx < len(entries) - 1:
                tk.Frame(self._conn_inner, bg=t["BORDER"], height=1).pack(fill="x")

    def _clear_conn_history(self):
        self._conn_history.clear()
        self._req_count.clear()
        self._update_conn_table()

    def _set_status(self, text, color):
        self._dot.config(fg=color)
        self._status_lbl.config(text=text, fg=color)

    def _on_close(self):
        if self._running:
            self._stop_server(silent=True)
        self.destroy()


if __name__ == "__main__":
    app = OrikLauncher()
    app.mainloop()
