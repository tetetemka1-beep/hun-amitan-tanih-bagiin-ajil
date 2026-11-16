"""Монгол хэлтэй ухаалаг камер. Ажиллуулах: python uhaalag_camera.py"""

from __future__ import annotations

import argparse
import io
import logging
import logging.handlers
import os
import queue
import sqlite3
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    from camera_alerts import SoundPlayer
    from camera_engine import CameraWorker, DEFAULT_CONFIDENCE, SPECIES, mirrored_packet
    from camera_store import DATA_DIR, Store, display_name, local_now, validate_details
except ImportError as error:
    raise SystemExit(
        f"Шаардлагатай сан дутуу байна: {error}\n"
        "Суулгах команд: python -m pip install -r requirements.txt"
    ) from error

BG = "#0b1120"
PANEL = "#131e32"
FIELD = "#1c2a43"
LINE = "#293954"
TEXT = "#edf3fc"
MUTED = "#91a4c1"
ACCENT = "#39c7aa"
BLUE = "#76a9ff"
ORANGE = "#f3b56b"
RED = "#ee8490"


def label(parent, text, size=13, color=TEXT, bold=False, **kwargs):
    return ctk.CTkLabel(parent, text=text, text_color=color,
                        font=ctk.CTkFont(family="Segoe UI", size=size,
                                         weight="bold" if bold else "normal"), **kwargs)


def button(parent, text, command, primary=False, **kwargs):
    return ctk.CTkButton(parent, text=text, command=command, height=36, corner_radius=8,
                         fg_color=ACCENT if primary else FIELD,
                         hover_color="#2baf95" if primary else "#2a3d5e",
                         text_color=BG if primary else TEXT,
                         font=("Segoe UI", 13, "bold"), **kwargs)


class SmartCameraApp(ctk.CTk):
    def __init__(self, store=None, source="0", worker_factory=CameraWorker):
        super().__init__()
        self.title("Ухаалаг камер · Хүн ба амьтан")
        scale = self._get_window_scaling()
        width = min(1320, int(self.winfo_screenwidth() / scale) - 40)
        height = min(860, int(self.winfo_screenheight() / scale) - 90)
        self.geometry(f"{width}x{height}")
        self.minsize(min(1080, width), min(680, height))
        self.configure(fg_color=BG)
        self.store = store or Store()
        self.worker_factory = worker_factory
        self.worker = None
        self.last_packet = None
        self.rendered_image = None
        self.preview_image = None
        self.enrollment_active = False
        self.stopping = False
        self.closing = False
        self.dialog = None
        self.selected_profile = None
        self.profiles_by_id = {}
        self.photo_index = 0
        self.sound_player = SoundPlayer()
        self.visible_notices = set()
        self.source = str(source)
        self.mirror_var = tk.BooleanVar(value=self.store.get_setting("mirror_preview", "0") == "1")
        self.human_notice_var = tk.BooleanVar(value=self.store.get_setting("human_notices", "1") == "1")
        self.animal_alarm_var = tk.BooleanVar(value=self.store.get_setting("animal_alarm", "1") == "1")
        self.status_var = tk.StringVar(value="Камераа эхлүүлж, хүн эсвэл амьтныг кадрт харуулна уу.")
        self.progress_var = tk.StringVar(value="Бүртгэл эхлээгүй")
        self.clock_var = tk.StringVar()
        self._overlay_font = self._load_font(17)
        self._small_font = self._load_font(14)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_sidebar()
        self._build_tabs()
        self._build_footer()
        self.refresh_profiles()
        self.refresh_events()
        self.refresh_buttons()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Escape>", lambda _event: self.stop_camera())
        self.bind("<Control-s>", lambda _event: self.snapshot())
        self.after(50, self.poll_worker)
        self.after(100, self.tick_clock)
        self.after(3000, self.tick_events)

    @staticmethod
    def _load_font(size):
        for path in ("C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
            if Path(path).is_file():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default(size=size)

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=BG, height=86, corner_radius=0)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=24, pady=(16, 0))
        header.grid_columnconfigure(1, weight=1)
        mark = ctk.CTkFrame(header, width=48, height=48, fg_color="#153d3b", corner_radius=14)
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        mark.grid_propagate(False)
        label(mark, "◉", 30, ACCENT).place(relx=0.5, rely=0.5, anchor="center")
        label(header, "УХААЛАГ КАМЕР", 24, bold=True).grid(row=0, column=1, sticky="w")
        label(header, "Хүн, амьтан илрүүлэх ба хувийн бүртгэл", 12, MUTED).grid(row=1, column=1, sticky="w")
        label(header, "Улаанбаатар · UTC+08:00", 11, MUTED).grid(row=0, column=2, sticky="e")
        label(header, "", 17, bold=True, textvariable=self.clock_var).grid(row=1, column=2, sticky="e")
        self.alert_bar = ctk.CTkFrame(header, fg_color=PANEL, corner_radius=10)
        self.alert_bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.alert_bar.grid_columnconfigure(0, weight=1)
        self.notice_widgets = {}
        for column, (kind, color) in enumerate((("unknown_human", RED), ("animal", ORANGE))):
            frame = ctk.CTkFrame(self.alert_bar, fg_color="transparent")
            frame.grid(row=0, column=column, sticky="ew", padx=8, pady=4)
            frame.grid_columnconfigure(0, weight=1)
            text = label(frame, "", 12, color, True, anchor="w", wraplength=300)
            text.grid(row=0, column=0, sticky="ew", padx=6)
            if kind == "unknown_human":
                self.notice_register_button = button(frame, "Шинэ хүн бүртгэх", self.register_from_notice,
                                                      primary=True, width=165)
                self.notice_register_button.grid(row=0, column=1, padx=8)
            button(frame, "×", lambda key=kind: self.dismiss_notice(key), width=30).grid(row=0, column=2)
            self.notice_widgets[kind] = (frame, text)
            frame.grid_remove()
        self.alert_bar.grid_remove()

    def _build_sidebar(self):
        side = ctk.CTkScrollableFrame(self, width=230, fg_color=PANEL, corner_radius=14)
        side.grid(row=1, column=0, sticky="ns", padx=(20, 12), pady=16)
        side.grid_columnconfigure(0, weight=1)
        label(side, "УДИРДЛАГА", 11, MUTED, True).grid(row=0, column=0, sticky="w", padx=10, pady=(12, 12))
        self.start_button = button(side, "▶   Камер эхлүүлэх", self.start_camera, True)
        self.start_button.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        self.stop_button = button(side, "■   Зогсоох", self.stop_camera)
        self.stop_button.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        self.snapshot_button = button(side, "Зураг хадгалах  ·  Ctrl+S", self.snapshot)
        self.snapshot_button.grid(row=3, column=0, sticky="ew", padx=8, pady=4)
        ctk.CTkFrame(side, height=1, fg_color=LINE).grid(row=4, column=0, sticky="ew", padx=10, pady=18)
        label(side, "ШИНЭ БҮРТГЭЛ", 11, MUTED, True).grid(row=5, column=0, sticky="w", padx=10)
        self.human_button = button(side, "Хүн бүртгэх   ·   50 зураг", self.new_registration)
        self.human_button.grid(row=6, column=0, sticky="ew", padx=8, pady=(12, 4))
        ctk.CTkSwitch(side, text="Амьтны дуут дохио", variable=self.animal_alarm_var,
                      font=("Segoe UI", 12), progress_color=ACCENT, command=self.change_alert_settings).grid(
                          row=7, column=0, sticky="w", padx=10, pady=(14, 4))
        ctk.CTkSwitch(side, text="Хүний мэдэгдэл", variable=self.human_notice_var,
                      font=("Segoe UI", 12), progress_color=ACCENT, command=self.change_alert_settings).grid(
                          row=8, column=0, sticky="w", padx=10, pady=(14, 8))
        ctk.CTkFrame(side, height=1, fg_color=LINE).grid(row=9, column=0, sticky="ew", padx=10, pady=18)
        button(side, "Хадгалсан файлууд", self.open_data_folder).grid(
            row=10, column=0, sticky="ew", padx=8, pady=4)
        button(side, "Ашиглах заавар", self.show_help).grid(row=11, column=0, sticky="ew", padx=8, pady=(4, 12))

    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(self, fg_color=BG, corner_radius=12,
                                  segmented_button_fg_color=PANEL,
                                  segmented_button_selected_color="#244b60",
                                  segmented_button_selected_hover_color="#2a586e",
                                  segmented_button_unselected_color=PANEL)
        self.tabs.grid(row=1, column=1, sticky="nsew", padx=(0, 20), pady=(0, 10))
        for name in ("Шууд камер", "Бүртгэлүүд", "Үйл явдал"):
            self.tabs.add(name)
        self._build_camera_tab(self.tabs.tab("Шууд камер"))
        self._build_registry_tab(self.tabs.tab("Бүртгэлүүд"))
        self._build_event_tab(self.tabs.tab("Үйл явдал"))

    def _build_camera_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        stats = ctk.CTkFrame(tab, fg_color="transparent")
        stats.grid(row=0, column=0, sticky="ew", pady=(4, 14))
        self.stat_labels = {}
        for column, (key, title, color) in enumerate((
                ("human", "КАДР ДАХЬ ХҮН", ACCENT), ("animal", "КАДР ДАХЬ АМЬТАН", ORANGE),
                ("fps", "AI ХУРД · FPS", BLUE), ("registered", "БҮРТГЭЛТЭЙ ХҮН", TEXT))):
            stats.grid_columnconfigure(column, weight=1, uniform="stat")
            card = ctk.CTkFrame(stats, fg_color=PANEL, corner_radius=12)
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 5, 0 if column == 3 else 5))
            label(card, title, 10, MUTED, True).pack(anchor="w", padx=16, pady=(13, 0))
            value = label(card, "0" if key == "registered" else "—", 30, color, True)
            value.pack(anchor="w", padx=16, pady=(0, 10))
            self.stat_labels[key] = value
        content = ctk.CTkFrame(tab, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        camera_card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=14)
        camera_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        camera_card.grid_columnconfigure(0, weight=1)
        camera_card.grid_rowconfigure(1, weight=1)
        self.live_label = label(camera_card, "●  КАМЕР ЗОГССОН", 12, MUTED, True)
        self.live_label.grid(row=0, column=0, sticky="w", padx=18, pady=12)
        self.mirror_switch = ctk.CTkSwitch(camera_card, text="Толины тусгал", variable=self.mirror_var,
                                          font=("Segoe UI", 12), progress_color=ACCENT,
                                          command=self.change_mirror)
        self.mirror_switch.grid(row=0, column=0, sticky="e", padx=18, pady=12)
        self.preview_host = ctk.CTkFrame(camera_card, fg_color="#080e19", corner_radius=0)
        self.preview_host.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.preview = label(self.preview_host, "◉\n\nКамерын дүрс энд харагдана\n\nЗүүн талын «Камер эхлүүлэх» товчийг дарна уу.",
                             15, MUTED, justify="center")
        self.preview.place(relx=0.5, rely=0.5, anchor="center")
        self.preview_host.bind("<Configure>", lambda _event: self.resize_preview())
        result_card = ctk.CTkFrame(content, fg_color=PANEL, corner_radius=14, width=240)
        result_card.grid(row=0, column=1, sticky="ns")
        result_card.grid_propagate(False)
        result_card.grid_columnconfigure(0, weight=1)
        result_card.grid_rowconfigure(1, weight=1)
        label(result_card, "ТАНИЛТЫН ҮР ДҮН", 11, MUTED, True).grid(
            row=0, column=0, sticky="w", padx=14, pady=14)
        self.results_text = ctk.CTkTextbox(result_card, fg_color="transparent", text_color=TEXT,
                                          font=("Segoe UI", 13), wrap="word", width=216)
        self.results_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 10))
        self.set_results_text("Камер эхлээгүй байна.\n\nХүн ногоон, амьтан улбар шар хүрээтэй харагдана.")

    def _build_tree(self, parent, columns, headings, widths):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Camera.Treeview", background=PANEL, foreground=TEXT,
                         fieldbackground=PANEL, rowheight=34, borderwidth=0, font=("Segoe UI", 11))
        style.configure("Camera.Treeview.Heading", background=FIELD, foreground=MUTED,
                         relief="flat", font=("Segoe UI", 10, "bold"), padding=8)
        style.map("Camera.Treeview", background=[("selected", "#285366")], foreground=[("selected", "#ffffff")])
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=10)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="headings", style="Camera.Treeview", selectmode="browse")
        tree.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        for key, heading, width in zip(columns, headings, widths):
            tree.heading(key, text=heading)
            tree.column(key, width=width, minwidth=55, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns", pady=8)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew", padx=8)
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        return frame, tree

    def _build_registry_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=8)
        toolbar.grid_columnconfigure(0, weight=1)
        self.registry_title = label(toolbar, "Бүртгэлийн сан", 19, bold=True)
        self.registry_title.grid(row=0, column=0, sticky="w")
        button(toolbar, "CSV экспорт", lambda: self.export_csv("profiles"), width=120).grid(row=0, column=1)
        frame, self.profile_tree = self._build_tree(tab, ("kind", "name", "photos"),
                                                    ("Төрөл", "Овог, нэр", "Зураг"), (90, 200, 60))
        frame.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.profile_tree.bind("<<TreeviewSelect>>", self.select_profile)
        editor = ctk.CTkScrollableFrame(tab, fg_color=PANEL, width=280, corner_radius=12)
        editor.grid(row=1, column=1, sticky="ns")
        editor.grid_columnconfigure(0, weight=1)
        self.photo_label = label(editor, "Бүртгэл сонгоно уу", 12, MUTED, width=248, height=160)
        self.photo_label.grid(row=0, column=0, padx=6, pady=(10, 0))
        navigation = ctk.CTkFrame(editor, fg_color="transparent")
        navigation.grid(row=1, column=0, pady=6)
        button(navigation, "‹", lambda: self.move_photo(-1), width=36).pack(side="left")
        self.photo_count_label = label(navigation, "—", 12, MUTED, width=120)
        self.photo_count_label.pack(side="left")
        button(navigation, "›", lambda: self.move_photo(1), width=36).pack(side="left")
        self.profile_info_label = label(editor, "", 11, MUTED, wraplength=250)
        self.profile_info_label.grid(row=2, column=0, padx=10, pady=4)
        self.edit_vars = {name: tk.StringVar() for name in ("surname", "name", "note")}
        for row, (key, title) in enumerate((("surname", "Овог"), ("name", "Нэр"), ("note", "Тэмдэглэл"))):
            label(editor, title, 11, MUTED).grid(row=3 + row * 2, column=0, sticky="w", padx=10, pady=(8, 2))
            ctk.CTkEntry(editor, textvariable=self.edit_vars[key], fg_color=FIELD, border_color=LINE).grid(
                row=4 + row * 2, column=0, sticky="ew", padx=8)
        self.edit_button = button(editor, "Өөрчлөлт хадгалах", self.edit_profile, True)
        self.edit_button.grid(row=9, column=0, sticky="ew", padx=8, pady=(14, 4))
        self.retake_button = button(editor, "Дахин зураг авах", self.retake_profile)
        self.retake_button.grid(row=10, column=0, sticky="ew", padx=8, pady=4)
        self.delete_button = button(editor, "Бүртгэл устгах", self.delete_profile)
        self.delete_button.configure(text_color=RED)
        self.delete_button.grid(row=11, column=0, sticky="ew", padx=8, pady=(4, 12))

    def _build_event_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=8)
        toolbar.grid_columnconfigure(0, weight=1)
        label(toolbar, "Сүүлийн 100 илрүүлэлт", 19, bold=True).grid(row=0, column=0, sticky="w")
        button(toolbar, "CSV экспорт", lambda: self.export_csv("events"), width=120).grid(row=0, column=1)
        frame, self.event_tree = self._build_tree(tab, ("time", "kind", "name", "confidence", "similarity"),
            ("Огноо, цаг · UTC+8", "Төрөл", "Үр дүн", "Илрүүлэлт", "Төстэй байдал"), (175, 75, 210, 95, 105))
        frame.grid(row=1, column=0, sticky="nsew")
        label(tab, "Ижил бүртгэл / төрөлд 10 секунд тутамд нэг мөр хадгална. Хувь нь хэмжсэн нарийвчлал биш.",
              11, MUTED).grid(row=2, column=0, sticky="w", pady=10)

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self.status_label = label(footer, "", 12, MUTED, textvariable=self.status_var, anchor="w")
        self.status_label.grid(row=0, column=0, sticky="ew", padx=20, pady=(8, 0))
        self.enrollment_bar = ctk.CTkProgressBar(footer, progress_color=ACCENT, fg_color=FIELD, height=6)
        self.enrollment_bar.grid(row=1, column=0, sticky="ew", padx=20, pady=6)
        self.enrollment_bar.set(0)
        label(footer, "", 11, MUTED, textvariable=self.progress_var, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=20, pady=(0, 8))
        self.cancel_button = button(footer, "Зураг авалтыг цуцлах", self.cancel_enrollment, width=180)
        self.cancel_button.grid(row=0, column=1, rowspan=3, padx=20, pady=12)

    def set_results_text(self, text):
        self.results_text.configure(state="normal")
        self.results_text.delete("1.0", "end")
        self.results_text.insert("1.0", text)
        self.results_text.configure(state="disabled")

    def refresh_buttons(self):
        running = self.worker is not None and self.worker.is_alive()
        ready = running and self.worker.ready and not self.stopping
        idle = ready and not self.enrollment_active and self.dialog is None
        for widget, enabled in ((self.start_button, not running), (self.stop_button, running and not self.stopping),
                (self.snapshot_button, ready), (self.human_button, idle), (self.notice_register_button, idle),
                (self.cancel_button, self.enrollment_active and not self.stopping),
                (self.edit_button, self.selected_profile is not None and not self.enrollment_active),
                (self.delete_button, self.selected_profile is not None and not self.enrollment_active),
                (self.retake_button, self.selected_profile is not None and idle)):
            widget.configure(state="normal" if enabled else "disabled")

    def start_camera(self):
        if self.worker is not None and self.worker.is_alive():
            return
        text = self.source.strip()
        if text.isdecimal():
            source = int(text)
        elif Path(text).is_file():
            source = str(Path(text).resolve())
        else:
            messagebox.showerror("Оролт буруу", "Камерын индекс (0, 1…) эсвэл байгаа бичлэгийн зам оруулна уу.", parent=self)
            return
        self.stopping = False
        self.last_packet = None
        self.rendered_image = None
        for kind in tuple(self.visible_notices):
            self.dismiss_notice(kind)
        self.worker = self.worker_factory(self.store, source, DEFAULT_CONFIDENCE)
        self.worker.start()
        self.live_label.configure(text="●  АЧААЛЖ БАЙНА", text_color=BLUE)
        self.status_var.set("AI загваруудыг бэлдэж байна. Анхны удаа интернетээс татна…")
        self.preview.configure(image=None, text="AI загварууд ачаалж байна…")
        self.progress_var.set("Бүртгэл эхлээгүй")
        self.enrollment_bar.set(0)
        self.refresh_buttons()

    def stop_camera(self):
        if self.worker is None:
            return
        self.stopping = True
        self.worker.stop_event.set()
        self.status_var.set("Камерыг зогсоож байна…")
        self.refresh_buttons()

    def change_mirror(self):
        try:
            self.store.set_setting("mirror_preview", "1" if self.mirror_var.get() else "0")
            self.status_var.set("Толины тусгал асаалттай." if self.mirror_var.get() else "Толины тусгал унтраалттай.")
        except sqlite3.Error as error:
            self.status_var.set(f"Толины тусгалын тохиргоог хадгалж чадсангүй: {error}")
        if self.last_packet is not None:
            self.render_packet(self.last_packet)

    def change_alert_settings(self):
        try:
            self.store.set_setting("human_notices", "1" if self.human_notice_var.get() else "0")
            self.store.set_setting("animal_alarm", "1" if self.animal_alarm_var.get() else "0")
            self.status_var.set("Мэдэгдэл, дохионы тохиргоог хадгаллаа.")
        except sqlite3.Error as error:
            self.status_var.set(f"Тохиргоог хадгалж чадсангүй: {error}")
        if not self.human_notice_var.get():
            self.dismiss_notice("unknown_human")

    def handle_alert(self, alert):
        kind = alert.get("kind")
        if kind not in self.notice_widgets or self.closing or self.stopping:
            return
        if kind == "unknown_human" and (not self.human_notice_var.get() or self.enrollment_active):
            return
        frame, text = self.notice_widgets[kind]
        text.configure(text=f"{alert['message']} · {local_now():%H:%M:%S}")
        self.visible_notices.add(kind)
        self.layout_notices()
        self.refresh_buttons()
        if kind == "unknown_human" or self.animal_alarm_var.get():
            if not self.sound_player.play(kind):
                self.bell()

    def dismiss_notice(self, kind):
        self.notice_widgets[kind][0].grid_remove()
        self.visible_notices.discard(kind)
        self.layout_notices()

    def layout_notices(self):
        if not self.visible_notices:
            self.alert_bar.grid_remove()
            return
        kinds = [kind for kind in ("unknown_human", "animal") if kind in self.visible_notices]
        self.alert_bar.grid_columnconfigure(0, weight=2 if len(kinds) == 2 else 1)
        self.alert_bar.grid_columnconfigure(1, weight=1 if len(kinds) == 2 else 0)
        for column, kind in enumerate(kinds):
            self.notice_widgets[kind][0].grid(row=0, column=column)
        self.alert_bar.grid()

    def register_from_notice(self):
        unknown = [obj for obj in self.last_packet.objects if obj.kind == "human" and
                   obj.embedding is not None and obj.profile_id is None] if self.last_packet else []
        if not unknown:
            messagebox.showinfo("Хүн бүртгэх", "Бүртгүүлэх хүний нүүрийг камерт дахин харуулна уу.", parent=self)
            return
        self.new_registration()

    def new_registration(self, profile=None):
        if self.enrollment_active or self.dialog is not None:
            return
        if self.worker is None or not self.worker.ready or self.stopping:
            messagebox.showinfo("Камер", "Эхлээд камераа ажиллуулна уу.", parent=self)
            return
        count = 50
        dialog = ctk.CTkToplevel(self)
        self.dialog = dialog
        dialog.title("Хүн бүртгэх")
        dialog.geometry("450x470")
        dialog.resizable(False, False)
        dialog.configure(fg_color=PANEL)
        dialog.transient(self)
        dialog.grab_set()
        dialog.grid_columnconfigure(0, weight=1)
        label(dialog, "Хүний овог, нэрийг оруулна уу", 19, bold=True).grid(
            row=0, column=0, padx=24, pady=(24, 8), sticky="w")
        info = f"Нүүрний {count} зураг автоматаар авна.\nКадрт ганцаараа байж, нүүрээ янз бүрийн өнцгөөс харуулна уу."
        label(dialog, info, 12, MUTED, wraplength=395, justify="left").grid(
            row=1, column=0, padx=24, pady=(0, 12), sticky="w")
        variables = {}
        for index, (key, title) in enumerate((("surname", "Овог"),
                                               ("name", "Нэр"), ("note", "Тэмдэглэл (заавал биш)"))):
            label(dialog, title, 12, MUTED).grid(row=2 + index * 2, column=0, padx=24, sticky="w", pady=(6, 2))
            variables[key] = tk.StringVar(value=profile[key] if profile else "")
            entry = ctk.CTkEntry(dialog, textvariable=variables[key], height=34, fg_color=FIELD, border_color=LINE)
            entry.grid(row=3 + index * 2, column=0, padx=24, sticky="ew")
            if index == 0:
                dialog.after(100, entry.focus_set)

        def close():
            self.dialog = None
            dialog.grab_release()
            dialog.destroy()
            self.refresh_buttons()

        def begin():
            details = {key: variable.get() for key, variable in variables.items()}
            details.update(kind="human", species="person")
            try:
                details = validate_details(details)
                if self.worker is None or not self.worker.ready or self.stopping:
                    raise ValueError("Камер зогссон байна. Дахин эхлүүлнэ үү.")
            except ValueError as error:
                messagebox.showerror("Бүртгэл", str(error), parent=dialog)
                return
            self.enrollment_active = True
            self.dismiss_notice("unknown_human")
            self.worker.command("enroll", (details, profile["id"] if profile else None))
            self.progress_var.set(f"0 / {count} зураг · Бүртгэл эхэлж байна…")
            self.enrollment_bar.set(0)
            self.tabs.set("Шууд камер")
            close()

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=8, column=0, sticky="ew", padx=24, pady=24)
        button(actions, "Цуцлах", close, width=105).pack(side="left")
        button(actions, f"{count} зураг авч эхлэх", begin, True, width=225).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Return>", lambda _event: begin())
        self.refresh_buttons()

    def cancel_enrollment(self):
        if self.worker and self.enrollment_active:
            self.worker.command("cancel")
            self.status_var.set("Зураг авалтыг цуцалж байна…")

    def refresh_profiles(self, select_id=None):
        profiles = self.store.profiles()
        self.profiles_by_id = {profile["id"]: profile for profile in profiles}
        previous = select_id or (self.selected_profile["id"] if self.selected_profile else None)
        self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in profiles:
            self.profile_tree.insert("", "end", iid=profile["id"], values=(
                "Хүн",
                display_name(profile), profile["photo_count"]))
        self.stat_labels["registered"].configure(text=str(len(profiles)))
        self.registry_title.configure(text=f"Хүний бүртгэл · {len(profiles)}")
        if previous in self.profiles_by_id:
            self.profile_tree.selection_set(previous)
            self.select_profile()
        else:
            self.selected_profile = None
            self.photo_label.configure(image=None, text="Бүртгэл сонгоно уу")
            self.photo_count_label.configure(text="—")
            self.profile_info_label.configure(text="")
            for variable in self.edit_vars.values():
                variable.set("")
        self.refresh_buttons()

    def select_profile(self, _event=None):
        selected = self.profile_tree.selection()
        if not selected or selected[0] not in self.profiles_by_id:
            return
        self.selected_profile = self.profiles_by_id[selected[0]]
        self.photo_index = 0
        for key, variable in self.edit_vars.items():
            variable.set(self.selected_profile[key])
        profile = self.selected_profile
        self.profile_info_label.configure(text=f"Хүн · {profile['created_at'][:10]}")
        self.show_profile_photo()
        self.refresh_buttons()

    def move_photo(self, direction):
        if self.selected_profile:
            self.photo_index = (self.photo_index + direction) % self.selected_profile["photo_count"]
            self.show_profile_photo()

    def show_profile_photo(self):
        photo = self.store.photo(self.selected_profile["id"], self.photo_index)
        if photo:
            image = Image.open(io.BytesIO(photo)).convert("RGB")
            image.thumbnail((245, 160))
            self.profile_photo = ctk.CTkImage(light_image=image, size=image.size)
            self.photo_label.configure(image=self.profile_photo, text="")
        self.photo_count_label.configure(text=f"{self.photo_index + 1} / {self.selected_profile['photo_count']} зураг")

    def edit_profile(self):
        if not self.selected_profile or self.enrollment_active:
            return
        details = dict(self.selected_profile)
        details.update({key: variable.get() for key, variable in self.edit_vars.items()})
        try:
            self.store.edit(details["id"], details)
            self.refresh_profiles(details["id"])
            self.reload_gallery()
            self.status_var.set("Бүртгэлийн өөрчлөлтийг хадгаллаа.")
        except (ValueError, OSError, sqlite3.Error) as error:
            messagebox.showerror("Хадгалах", str(error), parent=self)

    def retake_profile(self):
        if self.selected_profile:
            self.new_registration(profile=self.selected_profile)

    def delete_profile(self):
        if not self.selected_profile or self.enrollment_active:
            return
        name = display_name(self.selected_profile)
        if messagebox.askyesno("Бүртгэл устгах", f"«{name}» бүртгэл болон бүх зургийг устгах уу?", parent=self):
            try:
                self.store.delete(self.selected_profile["id"])
                self.refresh_profiles()
                self.reload_gallery()
                self.status_var.set(f"«{name}» бүртгэлийг устгалаа.")
            except sqlite3.Error as error:
                messagebox.showerror("Устгах", str(error), parent=self)

    def reload_gallery(self):
        if self.worker:
            self.worker.command("reload")

    def refresh_events(self):
        self.event_tree.delete(*self.event_tree.get_children())
        for event in self.store.events():
            similarity = f"{event['similarity']:.1%}" if event["similarity"] is not None else "—"
            self.event_tree.insert("", "end", values=(
                event["occurred_at"][:19].replace("T", " "), "Хүн" if event["kind"] == "human" else "Амьтан",
                event["label"], f"{event['confidence']:.1%}", similarity))

    def export_csv(self, table):
        path = filedialog.asksaveasfilename(parent=self, title="CSV экспорт",
                                           initialfile=f"{table}_{local_now():%Y%m%d}.csv",
                                           defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            try:
                self.store.export_csv(path, table)
                self.status_var.set(f"Экспорт хадгаллаа: {path}")
            except (OSError, sqlite3.Error) as error:
                messagebox.showerror("Экспорт", str(error), parent=self)

    def snapshot(self):
        if self.rendered_image is None or self.worker is None or not self.worker.ready:
            return
        try:
            folder = DATA_DIR / "snapshots"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"camera_{local_now():%Y%m%d_%H%M%S_%f}.jpg"
            self.rendered_image.save(path, quality=94)
            self.status_var.set(f"Зураг хадгаллаа: {path.name}")
        except OSError as error:
            messagebox.showerror("Зураг хадгалах", str(error), parent=self)

    def open_data_folder(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(DATA_DIR)
        else:
            messagebox.showinfo("Хадгалалтын хавтас", str(DATA_DIR), parent=self)

    def render_packet(self, packet):
        self.last_packet = packet
        display = mirrored_packet(packet) if self.mirror_var.get() else packet
        image = Image.fromarray(cv2.cvtColor(display.frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        details = []
        for obj in display.objects:
            color = ACCENT if obj.kind == "human" else ORANGE
            x1, y1, x2, y2 = obj.bbox
            draw.rectangle(obj.bbox, outline=color, width=3)
            title = f"{obj.label} · {obj.confidence:.0%}"
            bbox = draw.textbbox((0, 0), title, font=self._overlay_font)
            text_width = min(image.width - 8, bbox[2] - bbox[0] + 16)
            left = max(0, min(x1, image.width - text_width))
            top = max(0, y1 - 29)
            draw.rectangle((left, top, left + text_width, top + 29), fill=color)
            draw.text((left + 7, top + 3), title, fill=BG, font=self._overlay_font)
            similarity = ""
            if obj.similarity is not None:
                similarity = f"\nТөстэй байдал: {max(0, obj.similarity):.1%}"
            kind = "ХҮН" if obj.kind == "human" else "АМЬТАН"
            details.append(f"{kind} · {obj.label}\nИлрүүлэлт: {obj.confidence:.1%}{similarity}")
        timestamp = f"{packet.captured_at}  UTC+08"
        draw.rectangle((0, image.height - 28, min(image.width, 310), image.height), fill="#10192b")
        draw.text((8, image.height - 23), timestamp, font=self._small_font, fill=TEXT)
        self.rendered_image = image
        self.resize_preview()
        self.stat_labels["human"].configure(text=str(sum(obj.kind == "human" for obj in packet.objects)))
        self.stat_labels["animal"].configure(text=str(sum(obj.kind == "animal" for obj in packet.objects)))
        self.stat_labels["fps"].configure(text=f"{packet.fps:.1f}")
        self.set_results_text("\n\n────────────\n\n".join(details) if details else "Хүн, амьтан илрээгүй байна.")

    def resize_preview(self):
        if self.rendered_image is None:
            return
        # Tk dimensions are physical pixels; CTkImage sizes are logical pixels.
        scaling = self.preview_host._get_widget_scaling()
        width = max(1, int(self.preview_host.winfo_width() / scaling) - 8)
        height = max(1, int(self.preview_host.winfo_height() / scaling) - 8)
        ratio = min(width / self.rendered_image.width, height / self.rendered_image.height)
        size = (max(1, int(self.rendered_image.width * ratio)), max(1, int(self.rendered_image.height * ratio)))
        if self.preview_image is None:
            self.preview_image = ctk.CTkImage(light_image=self.rendered_image, size=size)
        else:
            self.preview_image.configure(light_image=self.rendered_image, size=size)
        self.preview.configure(image=self.preview_image, text="")

    def poll_worker(self):
        if self.closing:
            return
        if self.worker:
            try:
                while True:
                    event, value = self.worker.events.get_nowait()
                    if event == "status":
                        self.status_var.set(value)
                    elif event == "ready":
                        self.live_label.configure(text="●  ШУУД ДҮРС", text_color=ACCENT)
                        self.status_var.set("Камер ажиллаж байна · гарах / зогсоох: Esc")
                        self.refresh_buttons()
                    elif event == "progress":
                        count, total, message = value
                        self.enrollment_bar.set(count / total)
                        self.progress_var.set(f"{count} / {total} зураг · {message}")
                    elif event == "saved":
                        self.enrollment_active = False
                        self.dismiss_notice("unknown_human")
                        self.enrollment_bar.set(1)
                        self.progress_var.set("Бүх зураг, нэр, танилтын өгөгдлийг амжилттай хадгаллаа.")
                        self.status_var.set("Бүртгэл дууслаа. Танилтын санд шинэ бүртгэл нэмэгдлээ.")
                        self.refresh_profiles(value)
                    elif event == "cancelled":
                        self.enrollment_active = False
                        self.enrollment_bar.set(0)
                        self.progress_var.set("Зураг авалтыг цуцаллаа. Өмнөх бүртгэл хэвээр үлдсэн.")
                        self.refresh_buttons()
                    elif event == "alert":
                        self.handle_alert(value)
                    elif event == "registration_error":
                        self.enrollment_active = False
                        self.status_var.set(value)
                        self.refresh_buttons()
                    elif event == "error":
                        self.status_var.set(f"Алдаа: {value}")
                        messagebox.showerror("Камерын алдаа", value + "\n\nДэлгэрэнгүй: camera_data/app.log", parent=self)
                    elif event == "stopped":
                        self.enrollment_active = False
                        self.live_label.configure(text="●  КАМЕР ЗОГССОН", text_color=MUTED)
                        self.worker = None
                        for kind in tuple(self.visible_notices):
                            self.dismiss_notice(kind)
                        if self.stopping:
                            self.status_var.set("Камер зогссон. Дахин эхлүүлж болно.")
                        self.stopping = False
                        for key in ("human", "animal", "fps"):
                            self.stat_labels[key].configure(text="—")
                        self.refresh_buttons()
                        break
            except queue.Empty:
                pass
            if self.worker and not self.stopping:
                try:
                    self.render_packet(self.worker.frames.get_nowait())
                except queue.Empty:
                    pass
        self.after(50, self.poll_worker)

    def tick_clock(self):
        if not self.closing:
            self.clock_var.set(local_now().strftime("%Y-%m-%d   %H:%M:%S"))
            self.after(500, self.tick_clock)

    def tick_events(self):
        if not self.closing:
            if self.tabs.get() == "Үйл явдал":
                self.refresh_events()
            self.after(3000, self.tick_events)

    def show_help(self):
        messagebox.showinfo("Ашиглах заавар",
            "1. Камерын индексээ (ихэвчлэн 0) сонгоод эхлүүлнэ.\n"
            "2. Бүртгэлгүй нүүр дараалан 3 кадрт илэрвэл дээд хэсэгт мэдэгдэл гарна.\n"
            "3. Мэдэгдлийн «Шинэ хүн бүртгэх» товчоор овог, нэр оруулж 50 зураг авна.\n"
            "4. Бүртгэлүүд хэсэгт нэр засах, зураг үзэх, дахин авах, устгах боломжтой.\n"
            "5. Амьтан илэрвэл хоёр богино дуут дохио өгнө. Үргэлжлэн харагдвал 10 секунд тутам давтана.\n"
            "6. Хүний мэдэгдэл 30 секундийн зайтай. Нүүр харагдахгүй бол бүртгэлгүй гэж дүгнэхгүй.\n\n"
            "«Амьтны дуут дохио», «Хүний мэдэгдэл» тохиргоог зүүн талаас сольж болно.\n"
            "Open Images загвар: арслан, бар, тэмээ, ямаа, туулай болон бусад дэмжигдсэн амьтад.\n"
            "Дүрсний баруун дээд хэсгийн «Толины тусгал» тохиргоог асааж / унтрааж болно.\n\n"
            "Нүүрний зураг болон бүртгэл таны компьютерт camera_data хавтаст хадгалагдана.\n"
            "Анхны удаа AI загвар татахад интернет хэрэгтэй; дараа нь локал ажиллана.\n"
            "Ctrl+S: зураг хадгалах · Esc: камер зогсоох", parent=self)

    def on_close(self):
        self.closing = True
        self.sound_player.close()
        if self.dialog is not None:
            self.dialog.destroy()
            self.dialog = None
        if self.worker and self.worker.is_alive():
            self.worker.stop_event.set()
            self.status_var.set("Камерыг суллаж, программыг хааж байна…")
            self.after(100, self.wait_for_close)
        else:
            self.destroy()

    def wait_for_close(self):
        if self.worker and self.worker.is_alive():
            self.after(100, self.wait_for_close)
        else:
            self.destroy()


def main():
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Хүн, амьтан ялгах ухаалаг камер")
    parser.add_argument("--source", default="0", help="Камерын индекс эсвэл бичлэгийн зам")
    parser.add_argument("--prepare-models", action="store_true", help="AI загваруудыг татаж бэлдэх")
    args = parser.parse_args()
    if args.prepare_models:
        from setup_models import ensure_models
        ensure_models()
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(DATA_DIR / "app.log", maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = SmartCameraApp(source=args.source)
    if sys.platform == "win32":
        app.after(100, lambda: app.state("zoomed"))
    try:
        app.mainloop()
    except KeyboardInterrupt:
        app.on_close()
        app.mainloop()


if __name__ == "__main__":
    main()
