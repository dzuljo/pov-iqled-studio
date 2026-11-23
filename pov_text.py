import os
import glob
import numpy as np
import tkinter as tk
from tkinter import colorchooser
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageTk

def get_mac_fonts():
    search_dirs = [
        "/System/Library/Fonts/*.ttf",
        "/System/Library/Fonts/Supplemental/*.ttf",
        "/Library/Fonts/*.ttf",
        os.path.expanduser("~/Library/Fonts/*.ttf"),
        "/System/Library/Fonts/*.ttc",
        "/System/Library/Fonts/Supplemental/*.ttc",
    ]
    fonts = {}
    for pattern in search_dirs:
        for path in glob.glob(pattern):
            name = os.path.splitext(os.path.basename(path))[0]
            if any(skip in name for skip in ["LastResort", "AppleColorEmoji", "Symbol", "Dingbats", "Wingdings", "Webdings"]):
                continue
            fonts[name] = path
    if not fonts:
        fonts["Default"] = None
    return dict(sorted(fonts.items()))

def _render_single_line_mask(text, font_path, target_h, letter_spacing, bold_stroke):
    target_h = max(10, int(target_h))
    font_size = target_h
    font = None

    if font_path and os.path.exists(font_path):
        try:
            font = ImageFont.truetype(font_path, font_size)
            dummy = Image.new("L", (10, 10))
            d = ImageDraw.Draw(dummy)
            bbox = d.textbbox((0, 0), text, font=font, stroke_width=bold_stroke)
            txt_h = max(1, bbox[3] - bbox[1])
            font_size = max(8, int(font_size * (target_h / txt_h)))
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()

    dummy = Image.new("L", (10, 10))
    d = ImageDraw.Draw(dummy)
    char_widths = []
    min_top, max_bot = 999, -999

    for ch in text:
        bb = d.textbbox((0, 0), ch, font=font, stroke_width=bold_stroke)
        w = max(3, bb[2] - bb[0])
        char_widths.append(w)
        if ch.strip():
            min_top = min(min_top, bb[1])
            max_bot = max(max_bot, bb[3])

    if min_top > max_bot:
        min_top, max_bot = 0, target_h

    line_w = max(16, sum(char_widths) + max(0, len(text) - 1) * letter_spacing + 4)
    line_h = max(target_h, max_bot - min_top + 2)

    mask = Image.new("L", (line_w, line_h), 0)
    draw_m = ImageDraw.Draw(mask)
    y_pos = ((line_h - (max_bot - min_top)) // 2) - min_top
    x_pos = 2

    for ch, w in zip(text, char_widths):
        draw_m.text((x_pos, y_pos), ch, font=font, fill=255, stroke_width=bold_stroke, stroke_fill=255)
        x_pos += w + letter_spacing

    return mask

def _apply_gradient(mask_arr, gradient_mode):
    h, w = mask_arr.shape
    x_norm = np.linspace(0.0, 1.0, w, dtype=np.float32)
    if gradient_mode == "Rainbow":
        r = np.clip(np.abs(x_norm * 6.0 - 3.0) - 1.0, 0, 1) * 255
        g = np.clip(2.0 - np.abs(x_norm * 6.0 - 2.0), 0, 1) * 255
        b = np.clip(2.0 - np.abs(x_norm * 6.0 - 4.0), 0, 1) * 255
    elif gradient_mode == "Fire (Red-Yellow)":
        r = np.full(w, 255.0)
        g = x_norm * 220.0
        b = np.zeros(w)
    elif gradient_mode == "Neon (Cyan-Magenta)":
        r = x_norm * 255.0
        g = (1.0 - x_norm) * 255.0
        b = np.full(w, 255.0)
    else:
        r = np.full(w, 255.0)
        g = 200.0 + x_norm * 55.0
        b = x_norm * 220.0
    grad = np.stack([r, g, b], axis=-1)
    return (mask_arr[:, :, None] * grad[None, :, :]).astype(np.uint8)

def render_text_image(line1, line2="", font_path=None, leds=72,
                      color1=(255, 255, 255), color2=(0, 255, 255),
                      h1=24, h2=40, line_gap=4,
                      gradient_mode="Solid", pad_y=2, letter_spacing=3, bold_stroke=1):
    t1 = line1.strip()
    t2 = line2.strip()
    if not t1 and not t2:
        t1 = "POV POI"

    if not t2:
        target_h = max(16, leds - (pad_y * 2))
        m1 = _render_single_line_mask(t1, font_path, target_h, letter_spacing, bold_stroke)
        total_w = max(72, m1.width + 16)
        full_mask = Image.new("L", (total_w, leds), 0)
        full_mask.paste(m1, ((total_w - m1.width) // 2, (leds - m1.height) // 2))

        mask_arr = np.asarray(full_mask, dtype=np.float32) / 255.0
        rgb_arr = np.zeros((leds, total_w, 3), dtype=np.uint8)
        if gradient_mode == "Solid":
            for c in range(3):
                rgb_arr[:, :, c] = (mask_arr * color1[c]).astype(np.uint8)
        else:
            rgb_arr = _apply_gradient(mask_arr, gradient_mode)

        pil_rgb = Image.fromarray(rgb_arr, mode="RGB")
        rec_slices = max(120, min(1000, int(round(total_w * 1.1))))
        return pil_rgb, rec_slices

    m1 = _render_single_line_mask(t1 or " ", font_path, h1, letter_spacing, bold_stroke)
    m2 = _render_single_line_mask(t2, font_path, h2, letter_spacing, bold_stroke)

    total_w = max(72, max(m1.width, m2.width) + 16)
    combined_h = m1.height + line_gap + m2.height
    start_y = max(0, (leds - combined_h) // 2)

    mask1_full = Image.new("L", (total_w, leds), 0)
    mask2_full = Image.new("L", (total_w, leds), 0)

    mask1_full.paste(m1, ((total_w - m1.width) // 2, start_y))
    mask2_full.paste(m2, ((total_w - m2.width) // 2, start_y + m1.height + line_gap))

    arr1 = np.asarray(mask1_full, dtype=np.float32) / 255.0
    arr2 = np.asarray(mask2_full, dtype=np.float32) / 255.0
    rgb_arr = np.zeros((leds, total_w, 3), dtype=np.uint8)

    if gradient_mode == "Solid":
        for c in range(3):
            rgb_arr[:, :, c] = np.clip(arr1 * color1[c] + arr2 * color2[c], 0, 255).astype(np.uint8)
    else:
        comb_mask = np.clip(arr1 + arr2, 0.0, 1.0)
        rgb_arr = _apply_gradient(comb_mask, gradient_mode)

    pil_rgb = Image.fromarray(rgb_arr, mode="RGB")
    rec_slices = max(120, min(1000, int(round(total_w * 1.1))))
    return pil_rgb, rec_slices

class TextGeneratorDialog(ctk.CTkToplevel):
    def __init__(self, parent, leds=72, on_insert_callback=None):
        super().__init__(parent)
        self.title("POV Text Generator (1 or 2 Lines)")
        self.geometry("720x640")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.leds = leds
        self.on_insert = on_insert_callback
        self.fonts_map = get_mac_fonts()
        self.font_names = list(self.fonts_map.keys())
        self.color1 = (255, 255, 255)
        self.color2 = (0, 255, 255)
        self.preview_img = None
        self.rec_slices = 200

        default_font = next((f for f in ["Arial Bold", "Helvetica", "Futura", "Impact", "Arial"] if f in self.fonts_map), self.font_names[0])

        r_t1 = ctk.CTkFrame(self, fg_color="#23272e")
        r_t1.pack(fill="x", padx=15, pady=(10, 4))
        ctk.CTkLabel(r_t1, text="Line 1 (Top):", width=105, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        self.txt1_var = tk.StringVar(value="SKOPJE")
        self.txt1_var.trace_add("write", lambda *a: self._update_preview())
        e1 = ctk.CTkEntry(r_t1, textvariable=self.txt1_var, font=("Arial", 15, "bold"), height=34)
        e1.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        e1.focus_set()
        self.btn_col1 = ctk.CTkButton(r_t1, text="#FFFFFF", width=90, fg_color="#ffffff", text_color="#000000", command=lambda: self._pick_color(1))
        self.btn_col1.pack(side="right", padx=10)

        r_t2 = ctk.CTkFrame(self, fg_color="#23272e")
        r_t2.pack(fill="x", padx=15, pady=4)
        ctk.CTkLabel(r_t2, text="Line 2 (Bottom):", width=105, anchor="w", font=("Arial", 13, "bold")).pack(side="left", padx=10, pady=8)
        self.txt2_var = tk.StringVar(value="2026")
        self.txt2_var.trace_add("write", lambda *a: self._update_preview())
        e2 = ctk.CTkEntry(r_t2, textvariable=self.txt2_var, font=("Arial", 15, "bold"), height=34, placeholder_text="(Leave empty for single large line)")
        e2.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        self.btn_col2 = ctk.CTkButton(r_t2, text="#00FFFF", width=90, fg_color="#00ffff", text_color="#000000", command=lambda: self._pick_color(2))
        self.btn_col2.pack(side="right", padx=10)

        prev_f = ctk.CTkFrame(self, fg_color="#111111", height=110)
        prev_f.pack(fill="x", padx=15, pady=6)
        prev_f.pack_propagate(False)
        self.lbl_preview = tk.Label(prev_f, bg="#111111", bd=0)
        self.lbl_preview.pack(expand=True)

        grid_f = ctk.CTkFrame(self, fg_color="transparent")
        grid_f.pack(fill="both", expand=True, padx=15, pady=2)

        r_font = ctk.CTkFrame(grid_f, fg_color="#23272e")
        r_font.pack(fill="x", pady=3)
        ctk.CTkLabel(r_font, text="Font & Style:", width=110, anchor="w", font=("Arial", 12, "bold")).pack(side="left", padx=10, pady=6)
        self.font_var = tk.StringVar(value=default_font)
        ctk.CTkOptionMenu(r_font, variable=self.font_var, values=self.font_names, width=250, command=lambda _: self._update_preview()).pack(side="left", padx=6)

        self.grad_var = tk.StringVar(value="Solid")
        ctk.CTkOptionMenu(
            r_font, variable=self.grad_var,
            values=["Solid", "Rainbow", "Fire (Red-Yellow)", "Neon (Cyan-Magenta)", "Gold-White"],
            width=190, command=lambda _: self._update_preview()
        ).pack(side="right", padx=10)

        self.h1_var = tk.IntVar(value=24)
        self.h2_var = tk.IntVar(value=40)
        self.gap_var = tk.IntVar(value=4)
        self.bold_var = tk.IntVar(value=1)
        self.space_var = tk.IntVar(value=3)
        self.border_var = tk.IntVar(value=15)

        self._add_slider(grid_f, "Line 1 Height (LEDs):", self.h1_var, 12, 50)
        self._add_slider(grid_f, "Line 2 Height (LEDs):", self.h2_var, 12, 54)
        self._add_slider(grid_f, "Line Spacing (LEDs):", self.gap_var, 0, 16)
        self._add_slider(grid_f, "Bold Stroke:", self.bold_var, 0, 4)
        self._add_slider(grid_f, "Letter Spacing:", self.space_var, 0, 15)
        self._add_slider(grid_f, "Empty Border (%):", self.border_var, 0, 50)

        bot_f = ctk.CTkFrame(self, fg_color="transparent")
        bot_f.pack(fill="x", padx=15, pady=(6, 12))
        self.lbl_info = ctk.CTkLabel(bot_f, text="200 Slices @ 2000 FPS", text_color="#66d9ef", font=("Consolas", 11))
        self.lbl_info.pack(side="left", padx=2)

        ctk.CTkButton(
            bot_f, text="+ Insert Combined (1 Image)", width=195, height=36,
            font=("Arial", 12, "bold"), fg_color="#2e6f40", hover_color="#204e2d",
            command=self._insert_combined
        ).pack(side="right", padx=(6, 2))

        ctk.CTkButton(
            bot_f, text="📑 Split into 2 Images", width=165, height=36,
            font=("Arial", 12, "bold"), fg_color="#1f6aa5", hover_color="#144870",
            command=self._insert_split
        ).pack(side="right", padx=4)

        self._update_preview()

    def _add_slider(self, parent, label, var, min_v, max_v):
        row = ctk.CTkFrame(parent, fg_color="#23272e")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text=label, width=165, anchor="w", font=("Arial", 12)).pack(side="left", padx=10, pady=4)
        val_lbl = ctk.CTkLabel(row, text=str(var.get()), width=32, font=("Consolas", 12, "bold"))
        val_lbl.pack(side="right", padx=10)
        sld = ctk.CTkSlider(
            row, from_=min_v, to=max_v, number_of_steps=(max_v - min_v),
            variable=var, command=lambda v: (val_lbl.configure(text=str(int(round(v)))), self._update_preview())
        )
        sld.pack(side="right", fill="x", expand=True, padx=6)

    def _pick_color(self, line_num):
        init_c = self.color1 if line_num == 1 else self.color2
        rgb, hex_c = colorchooser.askcolor(initialcolor=init_c, title=f"Боја за Ред {line_num}")
        if rgb and hex_c:
            col_tuple = tuple(map(int, rgb))
            lum = sum(col_tuple)
            fg_t = "#000000" if lum > 380 else "#ffffff"
            if line_num == 1:
                self.color1 = col_tuple
                self.btn_col1.configure(text=hex_c.upper(), fg_color=hex_c, text_color=fg_t)
            else:
                self.color2 = col_tuple
                self.btn_col2.configure(text=hex_c.upper(), fg_color=hex_c, text_color=fg_t)
            self.grad_var.set("Solid")
            self._update_preview()

    def _update_preview(self):
        f_path = self.fonts_map.get(self.font_var.get())
        img, rec_sl = render_text_image(
            line1=self.txt1_var.get(),
            line2=self.txt2_var.get(),
            font_path=f_path,
            leds=self.leds,
            color1=self.color1,
            color2=self.color2,
            h1=self.h1_var.get(),
            h2=self.h2_var.get(),
            line_gap=self.gap_var.get(),
            gradient_mode=self.grad_var.get(),
            letter_spacing=self.space_var.get(),
            bold_stroke=self.bold_var.get()
        )
        self.preview_img = img
        self.rec_slices = rec_sl
        self.lbl_info.configure(text=f"{img.width}x{img.height}px | Suggested: {rec_sl} Slices")

        scale = min(650 / max(1, img.width), 86 / max(1, img.height))
        disp_w = max(10, int(img.width * scale))
        disp_h = max(10, int(img.height * scale))
        disp = img.resize((disp_w, disp_h), Image.Resampling.BILINEAR)
        tk_img = ImageTk.PhotoImage(disp)
        self.lbl_preview.configure(image=tk_img)
        self.lbl_preview.image = tk_img

    def _insert_combined(self):
        if self.preview_img and self.on_insert:
            t1 = self.txt1_var.get().strip()
            t2 = self.txt2_var.get().strip()
            name = f"{t1}_{t2}"[:14] if t2 else (t1[:14] or "Text")
            self.on_insert(self.preview_img, name, self.rec_slices, self.border_var.get())
        self.destroy()

    def _insert_split(self):
        if not self.on_insert:
            self.destroy()
            return
        f_path = self.fonts_map.get(self.font_var.get())
        t1 = self.txt1_var.get().strip()
        t2 = self.txt2_var.get().strip()
        if t1:
            img1, sl1 = render_text_image(t1, "", f_path, self.leds, self.color1, self.color1,
                                          gradient_mode=self.grad_var.get(), letter_spacing=self.space_var.get(), bold_stroke=self.bold_var.get())
            self.on_insert(img1, t1[:14], sl1, self.border_var.get())
        if t2:
            img2, sl2 = render_text_image(t2, "", f_path, self.leds, self.color2, self.color2,
                                          gradient_mode=self.grad_var.get(), letter_spacing=self.space_var.get(), bold_stroke=self.bold_var.get())
            self.on_insert(img2, t2[:14], sl2, self.border_var.get())
        self.destroy()
