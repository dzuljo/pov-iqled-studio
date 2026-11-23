import numpy as np
from PIL import Image, ImageDraw

class PolarRenderer:
    def __init__(self, size=440):
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.r_outer = (size // 2) - 16
        
        # Пред-пресметана координатна мрежа (X, Y) за максимална брзина
        y, x = np.ogrid[:size, :size]
        dx = x - self.cx
        dy = y - self.cy
        self.dist = np.sqrt(dx**2 + dy**2)
        # Агол од 0 до 360 степени (0 е горе, расте во насока на стрелките на часовникот)
        self.angle_deg = (np.degrees(np.arctan2(dx, -dy)) + 360.0) % 360.0

    def render_frame(self, rgb_slices, r1, sector_angle, current_angle_offset, active_slice_idx):
        """
        rgb_slices: numpy (slices, leds, 3) uint8
        r1: однос на внатрешен радиус (на пр. 0.450)
        sector_angle: агол на 1 слика во степени
        current_angle_offset: тековна ротација на поито
        active_slice_idx: индекс на активната колона за вертикалната лента
        """
        slices_count, leds_count, _ = rgb_slices.shape
        r_inner = self.r_outer * max(0.05, min(0.90, r1))
        ring_width = max(1.0, self.r_outer - r_inner)

        # Позадина (темна)
        canvas = np.full((self.size, self.size, 3), 18, dtype=np.uint8)

        # Маска за прстенот меѓу r_inner и r_outer
        mask = (self.dist >= r_inner) & (self.dist <= self.r_outer)

        # Мапирање на радиусот во LED индекс (0 = внатрешен, leds-1 = надворешен)
        led_idx = ((self.dist[mask] - r_inner) / ring_width * leds_count).astype(np.int32)
        led_idx = np.clip(led_idx, 0, leds_count - 1)

        # Мапирање на аголот во Slice индекс со природно повторување околу 360°
        rel_angle = (self.angle_deg[mask] - current_angle_offset + 360.0) % 360.0
        safe_sector = max(1.0, sector_angle)
        phase = (rel_angle % safe_sector) / safe_sector
        slice_idx = (phase * slices_count).astype(np.int32)
        slice_idx = np.clip(slice_idx, 0, slices_count - 1)

        canvas[mask] = rgb_slices[slice_idx, led_idx]

        img = Image.fromarray(canvas, mode="RGB")
        draw = ImageDraw.Draw(img)

        # Бели граници на внатрешниот и надворешниот радиус
        draw.ellipse(
            [self.cx - self.r_outer, self.cy - self.r_outer, self.cx + self.r_outer, self.cy + self.r_outer],
            outline=(230, 230, 230), width=2
        )
        draw.ellipse(
            [self.cx - r_inner, self.cy - r_inner, self.cx + r_inner, self.cy + r_inner],
            outline=(230, 230, 230), width=2
        )

        # Линија што ја покажува тековната позиција на стапот (LED лентата)
        rad = np.radians(current_angle_offset)
        x1 = self.cx + r_inner * np.sin(rad)
        y1 = self.cy - r_inner * np.cos(rad)
        x2 = self.cx + self.r_outer * np.sin(rad)
        y2 = self.cy - self.r_outer * np.cos(rad)
        draw.line([(x1, y1), (x2, y2)], fill=(255, 80, 80), width=2)

        return img

    def render_led_strip(self, rgb_slices, active_slice_idx, width=28, height=440):
        """Ја црта вертикалната LED лента десно од кругот (одоздола нагоре)."""
        leds_count = rgb_slices.shape[1]
        idx = active_slice_idx % rgb_slices.shape[0]
        col_pixels = rgb_slices[idx] # (leds, 3)

        strip_img = Image.new("RGB", (width, height), (18, 18, 18))
        draw = ImageDraw.Draw(strip_img)
        draw.rectangle([0, 0, width - 1, height - 1], outline=(80, 80, 80), width=1)

        step_h = (height - 8) / leds_count
        for i in range(leds_count):
            # LED 0 е долу (блиску до рачката), LED 71 е горе (врвот)
            y_bottom = height - 4 - (i * step_h)
            y_top = y_bottom - max(1.5, step_h - 1.0)
            r, g, b = map(int, col_pixels[i])
            draw.rectangle([4, y_top, width - 5, y_bottom], fill=(r, g, b))

        return strip_img
