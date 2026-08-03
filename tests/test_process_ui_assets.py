from pathlib import Path

from PIL import Image

from scripts.process_ui_assets import center_crop_resize, make_fine_pixel


def test_center_crop_resize_outputs_target_size(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    out = tmp_path / "out.png"
    Image.new("RGB", (1000, 700), (20, 30, 40)).save(src)

    center_crop_resize(src, out, (448, 368))

    with Image.open(out) as im:
        assert im.size == (448, 368)
        assert im.mode == "RGB"


def test_make_fine_pixel_keeps_final_size(tmp_path: Path) -> None:
    src = tmp_path / "source.png"
    out = tmp_path / "out.png"
    Image.new("RGB", (448, 368), (60, 70, 80)).save(src)

    make_fine_pixel(src, out, block=2, palette_colors=96)

    with Image.open(out) as im:
        assert im.size == (448, 368)
        assert im.mode == "RGB"
