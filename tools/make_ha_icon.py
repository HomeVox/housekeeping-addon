from __future__ import annotations

from pathlib import Path

from PIL import Image


def main() -> int:
    root = Path(r"Z:\Housekeeping")
    in_path = root / "icon.png"
    out_path = root / "icon.png"
    out_www = root / "www" / "icon.png"
    tmp_path = root / "icon.new.png"

    # Crop to the top portion (house + wifi) and scale up to fill the square.
    # This makes the add-on icon read larger in HA without changing HA UI sizing.
    crop_box = (120, 70, 120 + 784, 70 + 784)  # left, top, right, bottom

    with Image.open(in_path) as im:
        im = im.convert("RGBA")
        cropped = im.crop(crop_box)
        final = cropped.resize((1024, 1024), resample=Image.Resampling.LANCZOS)
        final.save(tmp_path, format="PNG")

    tmp_path.replace(out_path)
    out_www.parent.mkdir(parents=True, exist_ok=True)
    final_copy = Image.open(out_path)
    try:
        final_copy.save(out_www, format="PNG")
    finally:
        final_copy.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
