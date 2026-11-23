import os, json, time, threading
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser
import customtkinter as ctk
import numpy as np
from PIL import Image, ImageTk
from pov_engine import PovClip, extract_frames, export_sliki_h
from pov_polar import PolarRenderer
from pov_iqled import export_exepoi, upload_to_a3, find_a3_volume
from pov_text import TextGeneratorDialog

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
DEFAULT_SLIKI_H = "/Users/dzuljo/Documents/Arduino/PovPoiAPP/sliki.h"

class PovPoiApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("POV Poi Studio — iqLED Alpha-A3 RF (200 APA102)")
        self.geometry("1280x840")
        self.minsize(1160, 770)
        self.programs = [[], [], []]
        self.current_prog = 0
        self.selected_idx = -1
        self.selected_indices = set()
        self.is_playing = True
        self.view_speed = 0.25
        self.sim_time = 0.0
        self.last_frame_time = time.time()
        self.cached_slices = None
        self.renderer = PolarRenderer(size=430)
        self._build_top_bar()
        self._build_main_area()
        self._build_timeline_area()
        self._load_demo()
        self.after(20, self._animation_loop)

    def _load_demo(self):
        demo = Image.new("RGB", (200, 72), (0, 0, 0))
        px = demo.load()
        for x in range(200):
            for y in range(72):
                if (x // 25 + y // 18) % 2 == 0:
                    px[x, y] = (0, 220, 255) if y < 36 else (255, 60, 180)
        self.programs[0].append(PovClip(pil_image=demo, name="Demo_Ring"))
        self.selected_idx = 0
        self.selected_indices = {0}
        self._sync_controls_from_clip()
        self._refresh_timeline()

    def _build_top_bar(self):
        top = ctk.CTkFrame(self, height=52, corner_radius=8)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ctk.CTkButton(top, text="+ Add Image / GIF", width=140, command=self.add_media).pack(side="left", padx=5, pady=8)
        ctk.CTkButton(top, text="🔤 Add Text", width=110, fg_color="#4a356e", hover_color="#624691", command=self.open_text_gen).pack(side="left", padx=4)
        ctk.CTkButton(top, text="💾 Save", width=80, fg_color="#2b3a4a", command=self.save_project).pack(side="left", padx=4)
        ctk.CTkButton(top, text="📂 Load", width=80, fg_color="#2b3a4a", command=self.load_project).pack(side="left", padx=4)
        self.btn_play = ctk.CTkButton(top, text="⏸ Pause", width=85, fg_color="#3a4a2b", command=self.toggle_play)
        self.btn_play.pack(side="left", padx=(10, 4))
        ctk.CTkButton(top, text="🗑 Delete", width=85, fg_color="#5a2626", hover_color="#7a3030", command=self.delete_selected).pack(side="left", padx=4)
        ctk.CTkButton(top, text="⚡ Apply to All", width=120, fg_color="#7a5218", hover_color="#9c691f", command=self.apply_to_all_scenes).pack(side="left", padx=4)
        ctk.CTkButton(top, text="☰ Scene / Tools", width=125, fg_color="#333945", hover_color="#454d5e", command=self.open_scene_menu).pack(side="left", padx=4)
        self.btn_teensy = ctk.CTkButton(top, text="⬇ UPLOAD iqLED A3", width=155, font=("Arial", 13, "bold"), fg_color="#1f6aa5", hover_color="#144870", command=self.export_a3_exepoi)
        self.btn_teensy.pack(side="right", padx=(6, 10), pady=8)
        ctk.CTkButton(top, text="💾 Export .EXEPOI", width=135, font=("Arial", 13, "bold"), fg_color="#2e6f40", hover_color="#204e2d", command=self.save_a3_desktop).pack(side="right", padx=4, pady=8)
        ctk.CTkButton(top, text="📄 Export .H", width=95, font=("Arial", 13, "bold"), fg_color="#2e6f40", hover_color="#204e2d", command=self.export_h_ssd).pack(side="right", padx=4, pady=8)
        self.status_lbl = ctk.CTkLabel(top, text="Ready", text_color="#aaaaaa")
        self.status_lbl.pack(side="right", padx=10)

    def _build_main_area(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=10, pady=4)
        left_panel = ctk.CTkFrame(main, width=510, corner_radius=8)
        left_panel.pack(side="left", fill="y", padx=(0, 8))
        left_panel.pack_propagate(False)
        preview_row = ctk.CTkFrame(left_panel, fg_color="transparent")
        preview_row.pack(pady=(12, 4), padx=10)
        self.polar_label = tk.Label(preview_row, bg="#121212", bd=0)
        self.polar_label.pack(side="left", padx=(0, 10))
        self.strip_label = tk.Label(preview_row, bg="#121212", bd=0)
        self.strip_label.pack(side="left")
        self.physics_lbl = ctk.CTkLabel(left_panel, text="Angle: 0.0° | Cycle: 0.00s | delayUs: 0 µs", font=("Consolas", 12), text_color="#66d9ef")
        self.physics_lbl.pack(pady=(2, 8))

        right_panel = ctk.CTkFrame(main, corner_radius=8)
        right_panel.pack(side="right", fill="both", expand=True)
        cols_frame = ctk.CTkFrame(right_panel, fg_color="transparent")
        cols_frame.pack(fill="both", expand=True, padx=16, pady=12)
        col1 = ctk.CTkFrame(cols_frame, fg_color="transparent")
        col1.pack(side="left", fill="both", expand=True, padx=(0, 12))
        col2 = ctk.CTkFrame(cols_frame, fg_color="transparent")
        col2.pack(side="right", fill="both", expand=True, padx=(12, 0))

        self.ctrl_vars = {}
        self.ctrl_specs = {
            "fps": ("FPS (Hz)", 2000, 10, 20000, True),
            "spin_rps": ("Spin RPS", 2.0, 0.2, 10.0, False),
            "slices": ("Slices (px)", 200, 8, 512, True),
            "gamma": ("Gamma", 2.2, 0.5, 4.0, False),
            "view_speed": ("View Speed", 0.25, 0.05, 2.0, False),
            "len_sec": ("Len (sec)", 3.0, 0.01, 60.0, False),
            "brightness": ("BR (%)", 100, 5, 100, True),
            "border_pct": ("Border (%)", 0, 0, 80, True),
            "r1": ("R1 Ratio", 0.450, 0.10, 0.85, False),
            "leds": ("LEDs", 200, 16, 240, True),
            "remove_bg": ("Remove BG", 0, 0, 100, True),
        }
        for key in ["fps", "spin_rps", "slices", "gamma"]:
            self._add_param_row(col1, key)

        c_row = ctk.CTkFrame(col1, fg_color="#23272e", corner_radius=6)
        c_row.pack(fill="x", pady=5)
        ctk.CTkLabel(c_row, text="Color Tint", width=110, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        self.btn_color = ctk.CTkButton(c_row, text="#FFFFFF", width=110, fg_color="#ffffff", text_color="#000000", command=self.pick_color)
        self.btn_color.pack(side="right", padx=10, pady=6)
        self._add_param_row(col1, "view_speed")

        for key in ["len_sec", "brightness", "border_pct", "r1", "leds", "remove_bg"]:
            self._add_param_row(col2, key)

        fm_row = ctk.CTkFrame(col2, fg_color="#23272e", corner_radius=6)
        fm_row.pack(fill="x", pady=5)
        ctk.CTkLabel(fm_row, text="Orientation", width=110, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        self.btn_mirror = ctk.CTkButton(fm_row, text="⇄ Mirror", width=78, fg_color="#2b3a4a", command=self.toggle_mirror)
        self.btn_mirror.pack(side="right", padx=(4, 10), pady=6)
        self.btn_flip = ctk.CTkButton(fm_row, text="⇅ Flip V", width=78, fg_color="#2b3a4a", command=self.toggle_flip)
        self.btn_flip.pack(side="right", padx=3, pady=6)
        self.btn_rot = ctk.CTkButton(fm_row, text="↻ 90°", width=68, fg_color="#2b3a4a", command=self.rotate_90)
        self.btn_rot.pack(side="right", padx=3, pady=6)

        crop_row = ctk.CTkFrame(col2, fg_color="#23272e", corner_radius=6)
        crop_row.pack(fill="x", pady=5)
        ctk.CTkLabel(crop_row, text="Frame Crop", width=110, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        ctk.CTkButton(crop_row, text="↺ Reset", width=70, fg_color="#3a3f4b", command=self.reset_crop).pack(side="right", padx=(4, 10), pady=6)
        ctk.CTkButton(crop_row, text="✂️ Visual Crop", width=115, fg_color="#1f6aa5", command=self.open_visual_crop).pack(side="right", padx=4, pady=6)

    def _add_param_row(self, parent, key):
        label_txt, default_val, min_v, max_v, is_int = self.ctrl_specs[key]
        row = ctk.CTkFrame(parent, fg_color="#23272e", corner_radius=6)
        row.pack(fill="x", pady=5)
        ctk.CTkLabel(row, text=label_txt, width=110, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        var = tk.StringVar(value=str(default_val))
        self.ctrl_vars[key] = var
        step = 50 if key == "fps" else (4 if key == "slices" else (5 if key in ("brightness", "border_pct", "remove_bg") else (1 if is_int else 0.1)))
        if key == "r1": step = 0.01
        if key == "view_speed": step = 0.05
        if key == "len_sec": step = 0.01
        ctk.CTkButton(row, text="+", width=32, command=lambda k=key, s=step: self._adjust_param(k, s)).pack(side="right", padx=(2, 10), pady=6)
        entry = ctk.CTkEntry(row, textvariable=var, width=74, justify="center", font=("Consolas", 13))
        entry.pack(side="right", padx=4, pady=6)
        entry.bind("<Return>", lambda e, k=key: self._apply_manual_entry(k))
        entry.bind("<FocusOut>", lambda e, k=key: self._apply_manual_entry(k))
        ctk.CTkButton(row, text="-", width=32, command=lambda k=key, s=-step: self._adjust_param(k, s)).pack(side="right", padx=2, pady=6)

    def _build_timeline_area(self):
        bottom = ctk.CTkFrame(self, height=215, corner_radius=8)
        bottom.pack(fill="x", padx=10, pady=(4, 10))
        bottom.pack_propagate(False)
        prog_bar = ctk.CTkFrame(bottom, fg_color="transparent")
        prog_bar.pack(fill="x", padx=10, pady=(6, 2))
        self.prog_btns = [ctk.CTkButton(prog_bar, text=f"Program {i+1}", width=115, height=28, command=lambda idx=i: self.switch_program(idx)) for i in range(3)]
        for b in self.prog_btns: b.pack(side="left", padx=4)
        self.total_dur_lbl = ctk.CTkLabel(prog_bar, text="Total Duration: 0.0s", text_color="#bbbbbb")
        self.total_dur_lbl.pack(side="right", padx=10)
        self.cards_scroll = ctk.CTkScrollableFrame(bottom, height=112, orientation="horizontal", fg_color="#181a1f")
        self.cards_scroll.pack(fill="x", padx=10, pady=4)
        self.scrub_canvas = tk.Canvas(bottom, height=34, bg="#14161a", highlightthickness=1, highlightbackground="#333333")
        self.scrub_canvas.pack(fill="x", padx=10, pady=(2, 6))
        self.scrub_canvas.bind("<Button-1>", self._on_scrub_click)
        self.scrub_canvas.bind("<B1-Motion>", self._on_scrub_click)
        self.scrub_canvas.bind("<Configure>", lambda e: self._draw_scrub_bar())
        self._update_prog_buttons()

    def _get_current_clip(self):
        clips = self.programs[self.current_prog]
        return clips[self.selected_idx] if 0 <= self.selected_idx < len(clips) else None

    def _sync_controls_from_clip(self):
        c = self._get_current_clip()
        if not c:
            self.cached_slices = None
            return
        for k in ["fps", "spin_rps", "slices", "gamma", "len_sec", "brightness", "border_pct", "r1", "leds", "remove_bg"]:
            val = getattr(c, k)
            self.ctrl_vars[k].set(f"{val:.3f}" if k == "r1" else (f"{val:.2f}" if isinstance(val, float) else str(val)))
        self.ctrl_vars["view_speed"].set(f"{self.view_speed:.2f}")
        hex_c = "#%02x%02x%02x" % c.color_tint
        self.btn_color.configure(text=hex_c.upper(), fg_color=hex_c, text_color="#000000" if sum(c.color_tint) > 380 else "#ffffff")
        self.btn_flip.configure(fg_color="#1f6aa5" if c.flip_v else "#2b3a4a")
        self.btn_mirror.configure(fg_color="#1f6aa5" if c.mirror_h else "#2b3a4a")
        deg = getattr(c, "rotate_deg", 0)
        self.btn_rot.configure(text=f"↻ {deg}°" if deg else "↻ 90°", fg_color="#1f6aa5" if deg else "#2b3a4a")
        self.cached_slices = c.process_pixels()

    def _adjust_param(self, key, delta):
        try: cur = float(self.ctrl_vars[key].get())
        except ValueError: cur = self.ctrl_specs[key][1]
        self._set_param_value(key, cur + delta)

    def _apply_manual_entry(self, key):
        try: self._set_param_value(key, float(self.ctrl_vars[key].get()))
        except ValueError: self._sync_controls_from_clip()

    def _set_param_value(self, key, val):
        _, _, min_v, max_v, is_int = self.ctrl_specs[key]
        val = max(min_v, min(max_v, val))
        val = int(round(val)) if is_int else round(val, 3 if key == "r1" else 2)
        if key == "view_speed":
            self.view_speed = val
            self.ctrl_vars[key].set(f"{val:.2f}")
            return
        clips = self.programs[self.current_prog]
        targets = [clips[i] for i in self.selected_indices if 0 <= i < len(clips)] or ([self._get_current_clip()] if self._get_current_clip() else [])
        for c in targets: setattr(c, key, val)
        self._sync_controls_from_clip()
        self._refresh_timeline()

    def pick_color(self):
        c = self._get_current_clip()
        if not c: return
        res = colorchooser.askcolor(initialcolor="#%02x%02x%02x" % c.color_tint)
        if res and res[0]:
            rgb = tuple(int(x) for x in res[0])
            clips = self.programs[self.current_prog]
            for i in (self.selected_indices or {self.selected_idx}):
                if 0 <= i < len(clips): clips[i].color_tint = rgb
            self._sync_controls_from_clip()

    def toggle_flip(self):
        c = self._get_current_clip()
        if not c: return
        nv = not c.flip_v
        clips = self.programs[self.current_prog]
        for i in (self.selected_indices or {self.selected_idx}):
            if 0 <= i < len(clips): clips[i].flip_v = nv
        self._sync_controls_from_clip()

    def toggle_mirror(self):
        c = self._get_current_clip()
        if not c: return
        nv = not c.mirror_h
        clips = self.programs[self.current_prog]
        for i in (self.selected_indices or {self.selected_idx}):
            if 0 <= i < len(clips): clips[i].mirror_h = nv
        self._sync_controls_from_clip()

    def rotate_90(self):
        c = self._get_current_clip()
        if not c: return
        nd = (getattr(c, "rotate_deg", 0) + 90) % 360
        clips = self.programs[self.current_prog]
        for i in (self.selected_indices or {self.selected_idx}):
            if 0 <= i < len(clips): clips[i].rotate_deg = nd
        self._sync_controls_from_clip()

    def toggle_play(self):
        self.is_playing = not self.is_playing
        self.btn_play.configure(text="⏸ Pause" if self.is_playing else "▶ Play")

    def add_media(self):
        paths = filedialog.askopenfilenames(title="Select Images or GIF", filetypes=[("Images & GIF", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("All files", "*.*")])
        if not paths: return
        clips = self.programs[self.current_prog]
        for p in paths:
            frames = extract_frames(p)
            base = os.path.splitext(os.path.basename(p))[0]
            is_gif = len(frames) > 1
            for idx, fr in enumerate(frames):
                c = PovClip(pil_image=fr, name=f"{base}_{idx+1}" if is_gif else base)
                if is_gif:
                    c.slices = 72
                    c.len_sec = 0.05
                clips.append(c)
        self.selected_idx = len(clips) - 1
        self.selected_indices = {self.selected_idx}
        self._sync_controls_from_clip()
        self._refresh_timeline()

    def open_text_gen(self):
        c = self._get_current_clip()
        leds_cnt = c.leds if c else 200
        def on_insert(pil_img, name, rec_slices, border_pct=0):
            clips = self.programs[self.current_prog]
            nc = PovClip(pil_image=pil_img, name=name)
            nc.slices = max(72, min(512, int(rec_slices)))
            nc.border_pct = int(border_pct)
            nc.leds = leds_cnt
            clips.append(nc)
            self.selected_idx = len(clips) - 1
            self.selected_indices = {self.selected_idx}
            self._sync_controls_from_clip()
            self._refresh_timeline()
        TextGeneratorDialog(self, leds=leds_cnt, on_insert_callback=on_insert)

    def delete_selected(self):
        clips = self.programs[self.current_prog]
        if not clips: return
        for i in sorted(self.selected_indices or ({self.selected_idx} if self.selected_idx >= 0 else set()), reverse=True):
            if 0 <= i < len(clips): clips.pop(i)
        self.selected_idx = min(len(clips) - 1, max(0, self.selected_idx)) if clips else -1
        self.selected_indices = {self.selected_idx} if self.selected_idx >= 0 else set()
        self._sync_controls_from_clip()
        self._refresh_timeline()

    def apply_to_all_scenes(self):
        src = self._get_current_clip()
        clips = self.programs[self.current_prog]
        if not src or len(clips) < 2:
            messagebox.showinfo("Info", "Need at least 2 frames in the current program.")
            return
        for c in clips:
            for k in ["fps", "spin_rps", "slices", "gamma", "len_sec", "brightness", "border_pct", "r1", "leds", "remove_bg", "flip_v", "mirror_h", "rotate_deg", "rotate_deg", "crop_box"]:
                setattr(c, k, getattr(src, k))
            c.color_tint = src.color_tint
        self._sync_controls_from_clip()
        self._refresh_timeline()
        messagebox.showinfo("Applied", f"Settings applied to all {len(clips)} frames!")

    def reset_crop(self):
        c = self._get_current_clip()
        if not c: return
        c.crop_box = None
        self._sync_controls_from_clip()
        self._refresh_timeline()

    def open_visual_crop(self):
        clip = self._get_current_clip()
        if not clip: return
        win = ctk.CTkToplevel(self)
        win.title(f"Visual Crop — {clip.name}")
        win.geometry("540x610")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="Drag with mouse to select area (or Auto-Trim):", font=("Arial", 13, "bold")).pack(pady=(10, 6))
        cw, ch = 460, 460
        canvas = tk.Canvas(win, width=cw, height=ch, bg="#111111", cursor="crosshair", highlightthickness=1, highlightbackground="#4da6ff")
        canvas.pack(pady=4)
        tk_img = ImageTk.PhotoImage(clip.raw_image.resize((cw, ch), Image.Resampling.BILINEAR))
        canvas.image = tk_img
        canvas.create_image(0, 0, anchor="nw", image=tk_img)
        state = {"x0": 0, "y0": 0, "x1": cw, "y1": ch, "rect": None}
        if clip.crop_box and len(clip.crop_box) == 4:
            bx0, by0, bx1, by1 = clip.crop_box
            state.update({"x0": int(bx0*cw), "y0": int(by0*ch), "x1": int(bx1*cw), "y1": int(by1*ch)})
        def redraw_rect():
            if state["rect"]: canvas.delete(state["rect"])
            state["rect"] = canvas.create_rectangle(state["x0"], state["y0"], state["x1"], state["y1"], outline="#00ffcc", width=2, dash=(4, 2))
        redraw_rect()
        canvas.bind("<Button-1>", lambda e: (state.update({"x0": max(0, min(cw, e.x)), "y0": max(0, min(ch, e.y)), "x1": max(0, min(cw, e.x)), "y1": max(0, min(ch, e.y))}), redraw_rect()))
        canvas.bind("<B1-Motion>", lambda e: (state.update({"x1": max(0, min(cw, e.x)), "y1": max(0, min(ch, e.y))}), redraw_rect()))
        def auto_trim():
            arr = np.asarray(clip.raw_image, dtype=np.float32)
            h_i, w_i, _ = arr.shape
            bg = np.median(np.take(arr.reshape(-1, 3), (0, w_i - 1, (h_i - 1) * w_i, h_i * w_i - 1), axis=0), axis=0)
            ys, xs = np.where(np.linalg.norm(arr - bg, axis=-1) > 28.0)
            if len(xs) > 10 and len(ys) > 10:
                px, py = max(2, int((xs.max() - xs.min()) * 0.04)), max(2, int((ys.max() - ys.min()) * 0.04))
                state.update({"x0": int(max(0, xs.min() - px) / w_i * cw), "y0": int(max(0, ys.min() - py) / h_i * ch), "x1": int(min(w_i, xs.max() + px) / w_i * cw), "y1": int(min(h_i, ys.max() + py) / h_i * ch)})
                redraw_rect()
        def apply_crop(to_all=False):
            xa, xb, ya, yb = min(state["x0"], state["x1"]), max(state["x0"], state["x1"]), min(state["y0"], state["y1"]), max(state["y0"], state["y1"])
            box = (xa / cw, ya / ch, xb / cw, yb / ch) if (xb - xa) >= 8 and (yb - ya) >= 8 else None
            for c in (self.programs[self.current_prog] if to_all else [clip]): c.crop_box = box
            win.destroy(); self._sync_controls_from_clip(); self._refresh_timeline()
        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(bar, text="✨ Auto-Trim", width=115, fg_color="#2b5b6c", command=auto_trim).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Apply to This", width=120, fg_color="#2e6f40", command=lambda: apply_crop(False)).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="⚡ Apply to All", width=125, fg_color="#7a5218", command=lambda: apply_crop(True)).pack(side="left", padx=4)
        ctk.CTkButton(bar, text="Cancel", width=80, fg_color="#333333", command=win.destroy).pack(side="right", padx=4)

    def open_scene_menu(self):
        win = ctk.CTkToplevel(self); win.title("Scene & Batch Tools"); win.geometry("350x340"); win.resizable(False, False); win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text="Scene & Batch Tools", font=("Arial", 15, "bold")).pack(pady=(12, 8))
        def run(fn): win.destroy(); fn()
        for label, col, fn in [("📁 Import Image Folder", "#1f6aa5", self.import_folder), ("⬛ Add Black Pause Slot", "#2b3a4a", self.insert_black_slot), ("📋 Duplicate Scene", "#2e6f40", self.duplicate_selected), ("✂️ Decimate GIF Frames", "#2b5b6c", self.open_decimate_dialog), ("⚡ Apply Settings to All", "#7a5218", self.apply_to_all_scenes), ("🧹 Clear Entire Program", "#6e2424", self.clear_program)]:
            ctk.CTkButton(win, text=label, width=300, height=34, fg_color=col, command=lambda f=fn: run(f)).pack(pady=4)

    def open_decimate_dialog(self):
        clips = self.programs[self.current_prog]
        if len(clips) < 4: messagebox.showinfo("Info", "At least 4 frames required."); return
        win = ctk.CTkToplevel(self); win.title("Decimate Animation"); win.geometry("360x280"); win.resizable(False, False); win.transient(self); win.grab_set()
        ctk.CTkLabel(win, text=f"Current: {len(clips)} frames", font=("Arial", 14, "bold")).pack(pady=(12, 4))
        keep_speed = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(win, text="Keep same speed (auto-adjust Len sec)", variable=keep_speed).pack(pady=8)
        def run_dec(drop_every):
            old_len = len(clips)
            nc = [c for i, c in enumerate(clips) if (i + 1) % drop_every != 0]
            if keep_speed.get() and nc:
                for c in nc: c.len_sec = round(c.len_sec * (old_len / len(nc)), 3)
            self.programs[self.current_prog] = nc; self.selected_idx = 0 if nc else -1; self.selected_indices = {0} if nc else set(); win.destroy(); self._sync_controls_from_clip(); self._refresh_timeline()
        ctk.CTkButton(win, text="Drop every 2nd frame (keep 50%)", width=310, fg_color="#1f6aa5", command=lambda: run_dec(2)).pack(pady=4)
        ctk.CTkButton(win, text="Drop every 3rd frame (keep 67%)", width=310, fg_color="#2b5b6c", command=lambda: run_dec(3)).pack(pady=4)
        ctk.CTkButton(win, text="Drop every 5th frame (keep 80%)", width=310, fg_color="#2e6f40", command=lambda: run_dec(5)).pack(pady=4)

    def import_folder(self):
        folder = filedialog.askdirectory(title="Select Image Folder")
        if not folder: return
        clips = self.programs[self.current_prog]
        for f in sorted(fn for fn in os.listdir(folder) if fn.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"))):
            for fr in extract_frames(os.path.join(folder, f)): clips.append(PovClip(pil_image=fr, name=os.path.splitext(f)[0]))
        if clips: self.selected_idx = len(clips) - 1; self.selected_indices = {self.selected_idx}; self._sync_controls_from_clip(); self._refresh_timeline()

    def insert_black_slot(self):
        clips = self.programs[self.current_prog]
        c = PovClip(pil_image=Image.new("RGB", (72, 72), (0, 0, 0)), name="Black Pause"); c.len_sec = 1.0
        pos = (self.selected_idx + 1) if self.selected_idx >= 0 else len(clips)
        clips.insert(pos, c); self.selected_idx = pos; self.selected_indices = {pos}; self._sync_controls_from_clip(); self._refresh_timeline()

    def duplicate_selected(self):
        src = self._get_current_clip()
        if not src: return
        c = PovClip(pil_image=src.raw_image.copy(), name=src.name + "_copy")
        for k in ["fps", "spin_rps", "slices", "gamma", "len_sec", "brightness", "border_pct", "r1", "leds", "remove_bg", "flip_v", "mirror_h", "rotate_deg", "rotate_deg", "crop_box"]: setattr(c, k, getattr(src, k))
        c.color_tint = src.color_tint; pos = self.selected_idx + 1; self.programs[self.current_prog].insert(pos, c)
        self.selected_idx = pos; self.selected_indices = {pos}; self._sync_controls_from_clip(); self._refresh_timeline()

    def clear_program(self):
        if messagebox.askyesno("Confirm", "Clear all frames in the current program?"):
            self.programs[self.current_prog] = []; self.selected_idx, self.selected_indices = -1, set(); self._sync_controls_from_clip(); self._refresh_timeline()

    def on_card_click(self, event, idx):
        shift, cmd = (event.state & 0x0001) != 0, ((event.state & 0x0004) != 0 or (event.state & 0x0008) != 0)
        if shift and self.selected_idx >= 0: self.selected_indices = set(range(min(self.selected_idx, idx), max(self.selected_idx, idx) + 1))
        elif cmd:
            if idx in self.selected_indices and len(self.selected_indices) > 1: self.selected_indices.remove(idx)
            else: self.selected_indices.add(idx)
            self.selected_idx = idx
        else: self.selected_idx, self.selected_indices = idx, {idx}
        self._sync_controls_from_clip(); self._refresh_timeline()

    def switch_program(self, idx):
        self.current_prog = idx; clips = self.programs[self.current_prog]
        self.selected_idx = 0 if clips else -1; self.selected_indices = {0} if clips else set(); self.sim_time = 0.0
        self._update_prog_buttons(); self._sync_controls_from_clip(); self._refresh_timeline()

    def _update_prog_buttons(self):
        for i, b in enumerate(self.prog_btns): b.configure(fg_color="#1f6aa5" if i == self.current_prog else "#2b2f38", text_color="#ffffff" if i == self.current_prog else "#aaaaaa")

    def _refresh_timeline(self):
        for w in self.cards_scroll.winfo_children(): w.destroy()
        clips = self.programs[self.current_prog]
        for idx, clip in enumerate(clips):
            im, mul = (idx == self.selected_idx), (idx in self.selected_indices)
            card = ctk.CTkFrame(self.cards_scroll, width=105, height=102, corner_radius=6, fg_color="#2b3d52" if im else ("#4a3b22" if mul else "#252830"), border_width=2 if (im or mul) else 0, border_color="#4da6ff" if im else "#ffb86c")
            card.pack(side="left", padx=4, pady=2); card.pack_propagate(False)
            tk_thumb = ImageTk.PhotoImage(clip.raw_image.resize((88, 56), Image.Resampling.BILINEAR))
            li = tk.Label(card, image=tk_thumb, bg="#111111", bd=0); li.image = tk_thumb; li.pack(pady=(5, 2))
            sn = (clip.name[:11] + "..") if len(clip.name) > 13 else clip.name
            lt = ctk.CTkLabel(card, text=f"{idx+1}. {sn}\n{clip.len_sec:.2f}s", font=("Arial", 10), justify="center"); lt.pack()
            for w in (card, li, lt): w.bind("<Button-1>", lambda e, i=idx: self.on_card_click(e, i))
        tot_sec = sum(c.len_sec for c in clips); self.total_dur_lbl.configure(text=f"Total Duration: {tot_sec:.2f}s ({len(clips)} frames)")
        kb_used = (16384 + sum((c.slices * (c.leds * 4 + 4) + 64) for pr in self.programs for c in pr)) / 1024.0; kb_free = 65536.0 - kb_used
        col = "#ff5555" if kb_free < 0 else ("#ffb86c" if kb_free < 40 else "#50fa7b")
        sel = f" | Selected: {len(self.selected_indices)}" if len(self.selected_indices) > 1 else ""
        self.status_lbl.configure(text=f"Used: {kb_used:.1f} KB | Free: {kb_free:.1f} KB{sel}" if kb_free >= 0 else f"OVERFLOW by {abs(kb_free):.1f} KB!{sel}", text_color=col)
        self._draw_scrub_bar()

    def _draw_scrub_bar(self):
        self.scrub_canvas.delete("all"); w, h = self.scrub_canvas.winfo_width(), self.scrub_canvas.winfo_height()
        clips = self.programs[self.current_prog]; tot_sec = sum(c.len_sec for c in clips)
        if w <= 10 or tot_sec <= 0: return
        colors = ["#2e6f40", "#1f6aa5", "#8a4b27", "#5c3a7a", "#2b7a78"]; cx = 0.0
        for idx, c in enumerate(clips):
            sw = (c.len_sec / tot_sec) * w
            self.scrub_canvas.create_rectangle(cx, 2, cx + sw, h - 2, fill=colors[idx % len(colors)], outline="#ffffff" if idx == self.selected_idx else "#111111", width=1)
            if sw > 32: self.scrub_canvas.create_text(cx + sw / 2, h / 2, text=f"#{idx+1}", fill="#ffffff", font=("Arial", 10, "bold"))
            cx += sw
        self.scrub_canvas.create_line(((self.sim_time % tot_sec) / tot_sec) * w, 0, ((self.sim_time % tot_sec) / tot_sec) * w, h, fill="#ff4444", width=3)

    def _on_scrub_click(self, e):
        tot_sec = sum(c.len_sec for c in self.programs[self.current_prog]); w = max(1, self.scrub_canvas.winfo_width())
        if tot_sec > 0: self.sim_time = (max(0, min(w, e.x)) / w) * tot_sec; self._draw_scrub_bar()

    def save_project(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Project JSON", "*.json")])
        if not path: return
        data = [[{"image_path": c.image_path, "name": c.name, "fps": c.fps, "spin_rps": c.spin_rps, "slices": c.slices, "gamma": c.gamma, "brightness": c.brightness, "border_pct": c.border_pct, "r1": c.r1, "leds": c.leds, "len_sec": c.len_sec, "color_tint": list(c.color_tint), "flip_v": c.flip_v, "mirror_h": c.mirror_h, "remove_bg": c.remove_bg, "crop_box": list(c.crop_box) if c.crop_box else None} for c in p] for p in self.programs]
        with open(path, "w", encoding="utf-8") as f: json.dump(data, f, indent=2)
        messagebox.showinfo("Saved", "Project saved successfully.")

    def load_project(self):
        path = filedialog.askopenfilename(filetypes=[("Project JSON", "*.json")])
        if not path: return
        with open(path, "r", encoding="utf-8") as f: data = json.load(f)
        self.programs = [[], [], []]
        for pi, pd in enumerate(data[:3]):
            for it in pd:
                if it.get("image_path") and os.path.exists(it["image_path"]):
                    c = PovClip(image_path=it["image_path"], name=it.get("name", "Clip"))
                    for k in ["fps", "spin_rps", "slices", "gamma", "brightness", "border_pct", "r1", "leds", "len_sec", "remove_bg", "flip_v", "mirror_h", "rotate_deg"]:
                        if k in it: setattr(c, k, it[k])
                    if "color_tint" in it: c.color_tint = tuple(it["color_tint"])
                    if it.get("crop_box"): c.crop_box = tuple(it["crop_box"])
                    self.programs[pi].append(c)
        self.switch_program(0)

    def save_a3_desktop(self):
        out_path = os.path.expanduser("~/Desktop/POI_001.exepoi")
        try:
            fsize, count = export_exepoi(self.programs[0], out_path)
            self.status_lbl.configure(text=f"Saved: POI_001.exepoi ({fsize/1024:.1f} KB)", text_color="#50fa7b")
            messagebox.showinfo("Export Complete", f"✅ Зачувано на Desktop:\n{out_path}\nГолемина: {fsize / 1024:.1f} KB")
        except Exception as e:
            messagebox.showerror("Export Error", str(e))

    def export_a3_exepoi(self):
        try:
            if find_a3_volume():
                vol, fsize, count, ejected = upload_to_a3(self.programs[0], "POI_001.exepoi", auto_eject=True)
                self.status_lbl.configure(text=f"Uploaded to A3: {fsize/1024:.1f} KB", text_color="#50fa7b")
                ej_msg = "Дискот е безбедно исфрлен (Ejected) — можеш да го исклучиш USB кабелот!" if ejected else "Запишано на A3 (направи Eject пред исклучување)."
                messagebox.showinfo(
                    "iqLED Alpha-A3 Upload Complete",
                    f"✅ Успешно префрлено на iqLED Alpha-A3 RF!\n\n"
                    f"Програми/слики: {count}\n"
                    f"Големина: {fsize / 1024:.1f} KB\n"
                    f"Скриени macOS фајлови: Исчистени\n\n"
                    f"{ej_msg}"
                )
            else:
                out_path = os.path.expanduser("~/Desktop/POI_001.exepoi")
                fsize, count = export_exepoi(self.programs[0], out_path)
                self.status_lbl.configure(text=f"Saved Desktop: POI_001.exepoi", text_color="#ffb86c")
                messagebox.showinfo(
                    "Saved to Desktop (A3 не е приклучен)",
                    f"Alpha-A3 не е приклучен во USB Disk мод (UP+DOWN при приклучување).\n\n"
                    f"Фајлот е зачуван на Desktop:\n{out_path} ({fsize / 1024:.1f} KB)"
                )
        except Exception as e:
            messagebox.showerror("iqLED A3 Error", str(e))

    def export_h_ssd(self):
        path = filedialog.asksaveasfilename(initialfile="sliki.h", defaultextension=".h", filetypes=[("C Header", "*.h")])
        if not path: return
        fb = export_sliki_h(self.programs, path); messagebox.showinfo("Export Complete", f"sliki.h exported!\nFlash used: {fb / 1024:.1f} KB")

    def upload_to_teensy(self):
        self.btn_teensy.configure(state="disabled", text="⏳ Working...")
        def worker():
            try: fb = export_sliki_h(self.programs, DEFAULT_SLIKI_H); ok, msg = compile_and_upload(lambda s: self.after(0, lambda: self.status_lbl.configure(text=s)))
            except Exception as ex: fb, ok, msg = 0, False, str(ex)
            def done():
                self.btn_teensy.configure(state="normal", text="⬇ UPLOAD TEENSY"); self.status_lbl.configure(text=f"Teensy: {'OK' if ok else 'Error'} ({fb/1024:.1f} KB)")
                if ok: messagebox.showinfo("Teensy 3.2", msg)
                else: messagebox.showerror("Error", msg)
            self.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

    def _animation_loop(self):
        now = time.time(); dt, self.last_frame_time = now - self.last_frame_time, now
        clips = self.programs[self.current_prog]; tot_sec = sum(c.len_sec for c in clips)
        if self.is_playing and tot_sec > 0: self.sim_time = (self.sim_time + dt * self.view_speed) % tot_sec; self._draw_scrub_bar()
        ac, lt = self._get_current_clip(), self.sim_time
        if clips and tot_sec > 0:
            acc = 0.0
            for idx, c in enumerate(clips):
                if acc <= self.sim_time < acc + c.len_sec:
                    ac, lt = c, self.sim_time - acc
                    if idx != self.selected_idx and self.is_playing: self.selected_idx = idx; self._sync_controls_from_clip()
                    break
                acc += c.len_sec
        if ac and self.cached_slices is not None:
            phys = ac.get_physics(); ang = (lt * ac.spin_rps * 360.0) % 360.0; slc = int(lt * ac.fps) % max(1, ac.slices)
            tk_p = ImageTk.PhotoImage(self.renderer.render_frame(self.cached_slices, ac.r1, phys["sector_angle"], ang, slc))
            self.polar_label.configure(image=tk_p); self.polar_label.image = tk_p
            tk_s = ImageTk.PhotoImage(self.renderer.render_led_strip(self.cached_slices, slc))
            self.strip_label.configure(image=tk_s); self.strip_label.image = tk_s
            self.physics_lbl.configure(text=f"Angle: {phys['sector_angle']:.1f}° | Cycle: {phys['rev_time']:.2f}s | Frame: {phys['img_time']:.3f}s | delayUs: {phys['delay_us']} µs")
        self.after(20, self._animation_loop)

if __name__ == "__main__":
    PovPoiApp().mainloop()
