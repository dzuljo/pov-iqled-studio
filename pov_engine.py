import os
import numpy as np
from PIL import Image, ImageSequence

def extract_frames(filepath):
    img = Image.open(filepath)
    frames = []
    if getattr(img, "is_animated", False):
        for frame in ImageSequence.Iterator(img):
            rgba = frame.convert("RGBA")
            bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
            frames.append(Image.alpha_composite(bg, rgba).convert("RGB"))
    else:
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        frames.append(Image.alpha_composite(bg, rgba).convert("RGB"))
    return frames

class PovClip:
    def __init__(self, image_path=None, pil_image=None, name="Clip"):
        self.image_path = image_path
        self.name = name
        if pil_image is not None:
            self.raw_image = pil_image.convert("RGB")
        elif image_path:
            loaded = extract_frames(image_path)
            self.raw_image = loaded.pop(0) if loaded else Image.new("RGB", (72, 72), (0, 0, 0))
        else:
            self.raw_image = Image.new("RGB", (72, 72), (0, 0, 0))

        self.fps = 2000
        self.spin_rps = 2.0
        self.slices = 200
        self.gamma = 2.2
        self.brightness = 100
        self.border_pct = 0
        self.r1 = 0.450
        self.leds = 200
        self.len_sec = 3.0
        self.color_tint = (255, 255, 255)
        self.flip_v = False
        self.mirror_h = False
        self.rotate_deg = 0
        self.remove_bg = 0
        self.crop_box = None

    def get_physics(self):
        delay_us = int(round(1000000.0 / max(1, self.fps)))
        img_time = self.slices / float(max(1, self.fps))
        rev_time = 1.0 / max(0.05, self.spin_rps)
        sector_angle = (img_time / rev_time) * 360.0
        return {"delay_us": delay_us, "img_time": img_time, "rev_time": rev_time, "sector_angle": sector_angle}

    def process_pixels(self):
        work_img = self.raw_image.rotate(-self.rotate_deg, expand=True) if getattr(self, "rotate_deg", 0) else self.raw_image
        w_orig, h_orig = work_img.size

        if self.crop_box and len(self.crop_box) == 4:
            bx0, by0, bx1, by1 = self.crop_box
            x1 = max(0, min(w_orig - 4, int(round(bx0 * w_orig))))
            y1 = max(0, min(h_orig - 4, int(round(by0 * h_orig))))
            x2 = max(x1 + 4, min(w_orig, int(round(bx1 * w_orig))))
            y2 = max(y1 + 4, min(h_orig, int(round(by1 * h_orig))))
            work_img = work_img.crop((x1, y1, x2, y2))

        r1_leds = 0
        active_leds = self.leds

        pad_slices = int(round(self.slices * (self.border_pct / 100.0)))
        img_slices = max(1, self.slices - pad_slices)

        img = work_img.resize((img_slices, active_leds), Image.Resampling.LANCZOS)
        arr = np.asarray(img, dtype=np.float32)

        if self.remove_bg > 0:
            cutoff = (self.remove_bg / 100.0) * 180.0
            max_ch = np.max(arr, axis=-1)
            mask = np.clip((max_ch - cutoff * 0.7) / max(1.0, cutoff * 0.3), 0.0, 1.0)
            arr = arr * mask[:, :, None]

        if pad_slices > 0:
            left_pad = pad_slices // 2
            right_pad = pad_slices - left_pad
            arr = np.pad(arr, ((0, 0), (left_pad, right_pad), (0, 0)), mode="constant", constant_values=0)

        if r1_leds > 0:
            arr = np.pad(arr, ((r1_leds, 0), (0, 0), (0, 0)), mode="constant", constant_values=0)

        arr = np.clip(arr / 255.0, 0.0, 1.0)
        arr = np.power(arr, self.gamma) * (self.brightness / 100.0)
        arr = arr * (np.array(self.color_tint, dtype=np.float32) / 255.0)
        final_rgb = np.clip(arr * 255.0, 0, 255).astype(np.uint8)

        final_rgb = np.flipud(final_rgb)
        if self.flip_v: final_rgb = np.flipud(final_rgb)
        if self.mirror_h: final_rgb = np.fliplr(final_rgb)
        return np.transpose(final_rgb, (1, 0, 2))

def build_c_header(programs):
    pixel_data_bytes, palettes_flat = bytearray(), []
    slices_list, fps_list, dur_list, off_list = [], [], [], []
    prog_starts, prog_counts = [], []

    for prog in programs:
        prog_starts.append(len(slices_list))
        prog_counts.append(len(prog))
        for clip in prog:
            slices_rgb = clip.process_pixels()
            s_cnt, l_cnt, _ = slices_rgb.shape
            flat_pixels = slices_rgb.reshape(-1, 3)

            tmp_im = Image.fromarray(flat_pixels.reshape(1, -1, 3), mode="RGB")
            quant_im = tmp_im.quantize(colors=16, method=Image.Quantize.MEDIANCUT)
            pal_indices = np.asarray(quant_im, dtype=np.uint8).reshape(-1)
            raw_pal = quant_im.getpalette()[:48]
            pal_colors = [(raw_pal[i], raw_pal[i+1], raw_pal[i+2]) for i in range(0, len(raw_pal), 3)]
            while len(pal_colors) < 16:
                pal_colors.append((0, 0, 0))

            offset = len(pixel_data_bytes)
            for i in range(0, len(pal_indices), 2):
                hi = int(pal_indices[i]) & 0x0F
                lo = (int(pal_indices[i + 1]) & 0x0F) if (i + 1) < len(pal_indices) else 0
                pixel_data_bytes.append((hi << 4) | lo)

            for r, g, b in pal_colors[:16]:
                palettes_flat.append((r << 16) | (g << 8) | b)

            dur_ms = max(10, min(600000, int(round(clip.len_sec * 1000.0))))
            off_list.append(f"{offset}UL")
            slices_list.append(str(s_cnt))
            fps_list.append(str(int(clip.fps)))
            dur_list.append(f"{dur_ms}UL")

    total_imgs = len(slices_list)
    n_safe = max(1, total_imgs)
    b3, bn = f"{chr(91)}3{chr(93)}", f"{chr(91)}{n_safe}{chr(93)}"
    bp, bd = f"{chr(91)}{max(1, len(palettes_flat))}{chr(93)}", f"{chr(91)}{max(1, len(pixel_data_bytes))}{chr(93)}"

    lines = [
        "#pragma once", "#include <Arduino.h>", "#include <avr/pgmspace.h>", "",
        f"const uint16_t TOTAL_IMAGES = {total_imgs};",
        f"const uint16_t PROG_START{b3} = {{{', '.join(map(str, prog_starts))}}};",
        f"const uint16_t PROG_COUNT{b3} = {{{', '.join(map(str, prog_counts))}}};", "",
        f"const uint16_t IMG_SLICES{bn} PROGMEM = {{{', '.join(slices_list) if slices_list else '1'}}};",
        f"const uint16_t IMG_FPS{bn} PROGMEM = {{{', '.join(fps_list) if fps_list else '2000'}}};",
        f"const uint32_t IMG_DURATION_MS{bn} PROGMEM = {{{', '.join(dur_list) if dur_list else '1000UL'}}};",
        f"const uint32_t IMG_DATA_OFFSET{bn} PROGMEM = {{{', '.join(off_list) if off_list else '0UL'}}};", "",
        f"const uint32_t PALETTES{bp} PROGMEM = {{"
    ]
    lines.append("  0x000000" if not palettes_flat else "\n".join(f"  {', '.join(f'0x{c:06X}' for c in palettes_flat[i:i+16])}," for i in range(0, len(palettes_flat), 16)))
    lines += ["};", "", f"const uint8_t PIXEL_DATA{bd} PROGMEM = {{"]
    lines.append("  0x00" if not pixel_data_bytes else "\n".join(f"  {', '.join(f'0x{b:02X}' for b in pixel_data_bytes[i:i+24])}," for i in range(0, len(pixel_data_bytes), 24)))
    lines += ["};", ""]
    return "\n".join(lines)

def export_sliki_h(programs, out_path="/Users/dzuljo/Documents/Arduino/PovPoiAPP/sliki.h"):
    code = build_c_header(programs)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(code)
    return sum((c.slices * (c.leds // 2) + 64) for p in programs for c in p)
