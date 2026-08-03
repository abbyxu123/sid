"""Prepare small-screen UI assets for the ESP32 AMOLED firmware.

The source artwork stays high resolution. This script creates deterministic
448px-wide firmware images and optional fine-pixel previews for quick review.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = Path("/Users/beibeixv/Desktop/1.8尺寸UX UI- codex前端")
PROCESSED = ROOT / "assets/ui_small_screen/processed"
PREVIEWS = ROOT / "assets/ui_small_screen/tests"
FIRMWARE = ROOT / "firmware/esp32_amoled18/noon_cat_amoled18"


def center_crop_resize(src: Path, out: Path, size: tuple[int, int]) -> None:
    """Center-crop to target aspect ratio, resize, and save as RGB PNG."""
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        sw, sh = rgb.size
        tw, th = size
        src_aspect = sw / sh
        dst_aspect = tw / th
        if src_aspect > dst_aspect:
            nw = int(sh * dst_aspect)
            left = (sw - nw) // 2
            box = (left, 0, left + nw, sh)
        else:
            nh = int(sw / dst_aspect)
            top = (sh - nh) // 2
            box = (0, top, sw, top + nh)
        rgb.crop(box).resize(size, Image.Resampling.LANCZOS).save(out)


def make_fine_pixel(src: Path, out: Path, block: int = 2, palette_colors: int = 96) -> None:
    """Apply a subtle pixel-art pass without making the image blocky."""
    if block < 1:
        raise ValueError("block must be >= 1")
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        if block > 1:
            small = rgb.resize(
                (max(1, rgb.width // block), max(1, rgb.height // block)),
                Image.Resampling.BILINEAR,
            )
            if palette_colors:
                small = small.quantize(colors=palette_colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
            rgb = small.resize(rgb.size, Image.Resampling.NEAREST)
        elif palette_colors:
            rgb = rgb.quantize(colors=palette_colors, method=Image.Quantize.MEDIANCUT).convert("RGB")
        rgb.save(out)


def _rgb565_le(pixel: tuple[int, int, int]) -> tuple[int, int]:
    r, g, b = pixel
    value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return value & 0xFF, value >> 8


def write_lvgl_c(image_path: Path, c_path: Path, symbol: str) -> None:
    """Write an LVGL v8 TRUE_COLOR RGB565 little-endian image descriptor."""
    with Image.open(image_path) as im:
        rgb = im.convert("RGB")
        width, height = rgb.size
        data = bytearray()
        for pixel in rgb.getdata():
            lo, hi = _rgb565_le(pixel)
            data.extend((lo, hi))

    lines = [
        "#include <lvgl.h>",
        "",
        f"const uint8_t {symbol}_map[] = {{",
    ]
    row: list[str] = []
    for i, byte in enumerate(data):
        row.append(f"0x{byte:02x}")
        if len(row) == 16:
            lines.append("  " + ", ".join(row) + ",")
            row = []
    if row:
        lines.append("  " + ", ".join(row) + ",")
    lines.extend([
        "};",
        "",
        f"const lv_img_dsc_t {symbol} = {{",
        "  .header = {",
        "    .cf = LV_IMG_CF_TRUE_COLOR,",
        "    .always_zero = 0,",
        f"    .w = {width},",
        f"    .h = {height},",
        "  },",
        f"  .data_size = sizeof({symbol}_map),",
        f"  .data = {symbol}_map,",
        "};",
        "",
    ])
    c_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    PREVIEWS.mkdir(parents=True, exist_ok=True)

    home_src = UI_SOURCE / "室内场景/首图.png"
    council_src = UI_SOURCE / "室内场景/开会.png"
    if not home_src.exists() or not council_src.exists():
        raise FileNotFoundError("UI source pack is missing home or council artwork")

    home = PROCESSED / "splash_sofa_fine_pixel.png"
    council = PROCESSED / "council_fine_pixel.png"
    home_tmp = PROCESSED / "splash_sofa_base.png"
    council_tmp = PROCESSED / "council_base.png"

    center_crop_resize(home_src, home_tmp, (448, 368))
    center_crop_resize(council_src, council_tmp, (448, 252))
    make_fine_pixel(home_tmp, home, block=2, palette_colors=96)
    make_fine_pixel(council_tmp, council, block=2, palette_colors=96)
    make_fine_pixel(home_tmp, PREVIEWS / "home_fine_pixel_test.png", block=2, palette_colors=96)

    write_lvgl_c(home, FIRMWARE / "splash_sofa.c", "splash_sofa")
    write_lvgl_c(council, FIRMWARE / "council_img.c", "council_img")


if __name__ == "__main__":
    main()
