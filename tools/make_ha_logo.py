from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps


def _smart_crop_box(im: Image.Image, threshold: int = 60) -> tuple[int, int, int, int] | None:
    """
    Find a bounding box around "bright" pixels so the logo fills more of the square.
    Works well for dark backgrounds with a bright mark (like the current HomeVox logo).
    """
    g = ImageOps.grayscale(im)
    # Binary mask: 255 where pixel is "bright", else 0.
    m = g.point(lambda p: 255 if p >= threshold else 0, mode="L")
    bbox = m.getbbox()
    return bbox


def _expand_box(
    box: tuple[int, int, int, int], w: int, h: int, margin: float = 0.06
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    mx = int(w * margin)
    my = int(h * margin)
    left = max(0, left - mx)
    top = max(0, top - my)
    right = min(w, right + mx)
    bottom = min(h, bottom + my)
    return (left, top, right, bottom)


def main() -> int:
    root = Path(r"Z:\Housekeeping")

    in_path = root / "logo.png"
    out_path = root / "logo.png"
    out_www = root / "www" / "logo.png"
    tmp_path = root / "logo.new.png"

    with Image.open(in_path) as im:
        im = im.convert("RGBA")
        w, h = im.size
        box = _smart_crop_box(im, threshold=60)
        cropped = im if box is None else im.crop(_expand_box(box, w, h, margin=0.06))

        final = cropped.resize((1024, 1024), resample=Image.Resampling.LANCZOS)
        final.save(tmp_path, format="PNG")

    tmp_path.replace(out_path)
    out_www.parent.mkdir(parents=True, exist_ok=True)
    Image.open(out_path).save(out_www, format="PNG")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
