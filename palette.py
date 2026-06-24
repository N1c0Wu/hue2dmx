from __future__ import annotations
from typing import Dict, List, Tuple
import colorsys

Rgb = Tuple[int, int, int]

def _clamp_byte(x: float) -> int:
    return 0 if x < 0 else 255 if x > 255 else int(round(x))

def _rgb_to_hsv(rgb: Rgb) -> Tuple[float, float, float]:
    r, g, b = [c / 255.0 for c in rgb]
    return colorsys.rgb_to_hsv(r, g, b)

def _hsv_to_rgb(h: float, s: float, v: float) -> Rgb:
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return _clamp_byte(r*255), _clamp_byte(g*255), _clamp_byte(b*255)

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _lerp_hue_shortest(h1: float, h2: float, t: float) -> float:
    d = ((h2 - h1 + 0.5) % 1.0) - 0.5
    return (h1 + d*t) % 1.0

def _complement(rgb: Rgb) -> Rgb:
    h, s, v = _rgb_to_hsv(rgb)
    return _hsv_to_rgb((h + 0.5) % 1.0, s, v)

def build_two_lamp_palette(
    rgb_a: Rgb, rgb_b: Rgb, *, mode: str, max_distance: int, analogous_shift_deg: float = 20.0
) -> Tuple[List[Rgb], Dict[int, str]]:
    """
    Liefert: (liste_rgb, hex_map), wobei
      liste_rgb[i] = (R,G,B) und hex_map[i] = '#RRGGBB' für i in 0..max_distance-1.
    Modi: 'blend' | 'complementary' | 'analogous' (um Mittel-Hue ± shift).
    """
    n = max(1, int(max_distance))
    if mode == "complementary":
        rgb_a, rgb_b = _complement(rgb_a), _complement(rgb_b)

    if mode in ("blend", "complementary"):
        ha, sa, va = _rgb_to_hsv(rgb_a)
        hb, sb, vb = _rgb_to_hsv(rgb_b)
        lst, hex_map = [], {}
        for i in range(n):
            t = 0.0 if n == 1 else i / (n - 1)
            h = _lerp_hue_shortest(ha, hb, t)
            s = _lerp(sa, sb, t)
            v = _lerp(va, vb, t)
            R, G, B = _hsv_to_rgb(h, s, v)
            lst.append((R, G, B)); hex_map[i] = f"#{R:02X}{G:02X}{B:02X}"
        return lst, hex_map

    # analogous
    ha, sa, va = _rgb_to_hsv(rgb_a); hb, sb, vb = _rgb_to_hsv(rgb_b)
    h_mid = _lerp_hue_shortest(ha, hb, 0.5); s_mid = (sa+sb)/2.0; v_mid = (va+vb)/2.0
    shift = (analogous_shift_deg / 360.0); h1, h2 = (h_mid - shift) % 1.0, (h_mid + shift) % 1.0
    lst, hex_map = [], {}
    for i in range(n):
        t = 0.0 if n == 1 else i / (n - 1)
        h = _lerp_hue_shortest(h1, h2, t)
        R, G, B = _hsv_to_rgb(h, s_mid, v_mid)
        lst.append((R, G, B)); hex_map[i] = f"#{R:02X}{G:02X}{B:02X}"
    return lst, hex_map
