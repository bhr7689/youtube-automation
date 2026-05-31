from pathlib import Path
from PIL import Image
from colorthief import ColorThief
import io


def rgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def extract_palette(image_path=None, image_url=None, color_count=6):
    if image_path and Path(image_path).exists():
        ct = ColorThief(image_path)
    elif image_url:
        import httpx
        try:
            resp = httpx.get(image_url, timeout=10, follow_redirects=True)
            ct = ColorThief(io.BytesIO(resp.content))
        except Exception:
            return _empty_palette()
    else:
        return _empty_palette()

    try:
        dominant = rgb_to_hex(ct.get_color(quality=1))
        palette = [rgb_to_hex(c) for c in ct.get_palette(color_count=color_count, quality=1)]
    except Exception:
        return _empty_palette()

    r, g, b = int(dominant[1:3], 16), int(dominant[3:5], 16), int(dominant[5:7], 16)
    if r > b + 30:
        temperature = "warm"
    elif b > r + 30:
        temperature = "cool"
    else:
        temperature = "neutral"

    brightnesses = []
    for hex_c in palette:
        rr, gg, bb = int(hex_c[1:3],16), int(hex_c[3:5],16), int(hex_c[5:7],16)
        brightnesses.append(0.299*rr + 0.587*gg + 0.114*bb)
    if len(brightnesses) >= 2:
        cr = max(brightnesses) - min(brightnesses)
        contrast_est = "very_high" if cr > 150 else ("high" if cr > 100 else ("medium" if cr > 50 else "low"))
    else:
        contrast_est = "unknown"

    return {"dominant": dominant, "palette": palette, "temperature": temperature, "contrast_est": contrast_est}


def _empty_palette():
    return {"dominant": None, "palette": [], "temperature": "unknown", "contrast_est": "unknown"}
