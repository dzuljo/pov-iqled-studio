import os
import struct
import subprocess
import numpy as np

A3_VOLUME_PATH = "/Volumes/NO NAME"

def _stm32_crc32(data12: bytes) -> int:
    crc = 0xFFFFFFFF
    for w in struct.unpack("<3I", data12[:12]):
        crc ^= w
        for _ in range(32):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc

def find_a3_volume():
    if os.path.isdir(A3_VOLUME_PATH):
        if os.path.exists(os.path.join(A3_VOLUME_PATH, "Mode.txt")) or os.path.exists(os.path.join(A3_VOLUME_PATH, "Driver type.txt")):
            return A3_VOLUME_PATH
    for vol in os.listdir("/Volumes"):
        vp = os.path.join("/Volumes", vol)
        if os.path.isdir(vp) and vol != "Macintosh HD":
            if os.path.exists(os.path.join(vp, "Driver type.txt")) or os.path.exists(os.path.join(vp, "Mode.txt")):
                return vp
    return None

def _build_program_block(clip, img_index, total_imgs, led_brightness_byte=0xEC):
    """
    100% идентичен Corona / iqLED Alpha-A3 блок (68 бајти = 0x44 header + SPI слајсови):
      +0x00 (4B): total_imgs (uint32 LE)
      +0x04 (4B): img_index 1-based (uint32 LE)  <-- offset табелата на 0x2010 покажува тука (+0x04)!
      +0x08 (2B): fps (uint16 LE)
      +0x0A (4B): duration_ms (uint32 LE)
      +0x0E (2B): num_pixels (uint16 LE)
      +0x10 (2B): num_slices (uint16 LE)
      +0x12 (6B): b"APA102"
      +0x18 (4B): 0x00000000
      +0x1C (4B): data_size = num_slices * (num_pixels * 4 + 12) (uint32 LE)
      +0x20..0x43 (36B): zeros (вкупно 0x44 = 68 бајти пред слајсовите!)
    """
    slices_rgb = clip.process_pixels()  # (slices, leds, 3) во RGB
    num_slices, num_pixels, _ = slices_rgb.shape

    fps = max(1, min(65535, int(round(clip.fps))))
    dur_ms = max(10, min(36000000, int(round(clip.len_sec * 1000.0))))

    bgr = slices_rgb[:, :, ::-1]
    alpha_col = np.full((num_slices, num_pixels, 1), led_brightness_byte, dtype=np.uint8)
    apa_pixels = np.concatenate([alpha_col, bgr], axis=-1).reshape(num_slices, num_pixels * 4)

    start_frame = np.zeros((num_slices, 4), dtype=np.uint8)
    end_frame = np.tile(np.array([0xFF, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x00, 0x00], dtype=np.uint8), (num_slices, 1))

    full_slices = np.hstack([start_frame, apa_pixels, end_frame]).tobytes()
    data_size = len(full_slices)

    prog_hdr = bytearray(0x44)
    struct.pack_into("<I", prog_hdr, 0x00, total_imgs)
    struct.pack_into("<I", prog_hdr, 0x04, img_index)
    struct.pack_into("<H", prog_hdr, 0x08, fps)
    struct.pack_into("<I", prog_hdr, 0x0A, dur_ms)
    struct.pack_into("<H", prog_hdr, 0x0E, num_pixels)
    struct.pack_into("<H", prog_hdr, 0x10, num_slices)
    prog_hdr[0x12:0x18] = b"APA102"
    struct.pack_into("<I", prog_hdr, 0x1C, data_size)

    return bytes(prog_hdr) + full_slices

def export_exepoi(clips, out_path):
    if not clips:
        raise ValueError("Нема додадено ниту една слика/текст во Program 1!")

    clips = clips[:128]
    total_imgs = len(clips)

    header = bytearray(0x4000)
    header[0x00:0x02] = b"\xAA\xAB"

    # Блок 1 почнува на 0x4010 (по 16 нули на 0x4000..0x400F),
    # па неговото поле img_index (+0x04) е точно на 0x4014!
    block_start = 0x4010
    blocks = []

    for idx, clip in enumerate(clips, start=1):
        dur_ms = max(10, min(36000000, int(round(clip.len_sec * 1000.0))))
        struct.pack_into("<I", header, 0x0014 + (idx - 1) * 4, dur_ms)
        struct.pack_into("<I", header, 0x2010 + (idx - 1) * 4, block_start + 4)

        block = _build_program_block(clip, idx, total_imgs)
        blocks.append(block)
        block_start += len(block)

    payload = b"".join(blocks)
    total_file_size = 0x4010 + len(payload)

    struct.pack_into(">I", header, 0x08, total_file_size)
    # STM32 хардверски CRC-32 на првите 12 бајти (0x00..0x0B) запишан на 0x0C..0x0F
    struct.pack_into(">I", header, 0x0C, _stm32_crc32(bytes(header[:12])))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(header)
        f.write(b"\x00" * 0x10)  # 16 бајти (0x4000..0x400F)
        f.write(payload)

    return os.path.getsize(out_path), total_imgs

def upload_to_a3(clips, filename="POI_001.exepoi", auto_eject=True):
    vol = find_a3_volume()
    if not vol:
        raise RuntimeError("iqLED Alpha-A3 RF не е пронајден!")

    for fn in os.listdir(vol):
        if fn.lower().endswith(".exepoi"):
            try:
                os.remove(os.path.join(vol, fn))
            except Exception:
                pass

    target_file = os.path.join(vol, filename)
    fsize, count = export_exepoi(clips, target_file)

    try:
        subprocess.run(["dot_clean", "-m", vol], capture_output=True, check=False)
    except Exception:
        pass
    os.sync()

    ejected = False
    if auto_eject:
        res = subprocess.run(["diskutil", "eject", vol], capture_output=True, text=True)
        ejected = (res.returncode == 0)

    return vol, fsize, count, ejected
