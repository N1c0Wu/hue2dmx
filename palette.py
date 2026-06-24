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
    rgb_a: Rgb, rgb_b: Rgb, *, mode: str, max_distance: int, analogous_shift_deg: float = 20.0, interpolation: str = "smooth"
) -> Tuple[List[Rgb], Dict[int, str]]:
    """
    Liefert: (liste_rgb, hex_map), wobei
      liste_rgb[i] = (R,G,B) und hex_map[i] = '#RRGGBB' für i in 0..max_distance-1.
    Modi: 'blend' | 'complementary' | 'analogous' | 'to_complement' | 'triadic' | 'split_complementary' | 'tetradic'
    """
    n = max(1, int(max_distance))
    lst = []
    hex_map = {}

    ha, sa, va = _rgb_to_hsv(rgb_a)
    hb, sb, vb = _rgb_to_hsv(rgb_b)

    # Generate the "target hues/colors" we are interpolating across
    colors_hsv = []
    
    if mode == "blend":
        colors_hsv = [(ha, sa, va), (hb, sb, vb)]
    elif mode == "complementary":
        colors_hsv = [((ha + 0.5) % 1.0, sa, va), ((hb + 0.5) % 1.0, sb, vb)]
    elif mode == "analogous":
        h_mid = _lerp_hue_shortest(ha, hb, 0.5)
        s_mid = (sa + sb) / 2.0
        v_mid = (va + vb) / 2.0
        shift = analogous_shift_deg / 360.0
        colors_hsv = [((h_mid - shift) % 1.0, s_mid, v_mid), ((h_mid + shift) % 1.0, s_mid, v_mid)]
    elif mode == "to_complement":
        colors_hsv = [(ha, sa, va), ((ha + 0.5) % 1.0, sa, va)]
    elif mode == "triadic":
        colors_hsv = [(ha, sa, va), ((ha + 1/3) % 1.0, sa, va), ((ha + 2/3) % 1.0, sa, va)]
    elif mode == "split_complementary":
        colors_hsv = [(ha, sa, va), ((ha + 150/360) % 1.0, sa, va), ((ha + 210/360) % 1.0, sa, va)]
    elif mode == "tetradic":
        colors_hsv = [(ha, sa, va), ((ha + 90/360) % 1.0, sa, va), ((ha + 180/360) % 1.0, sa, va), ((ha + 270/360) % 1.0, sa, va)]
    else:
        colors_hsv = [(ha, sa, va), (hb, sb, vb)] # fallback to blend

    num_colors = len(colors_hsv)

    for i in range(n):
        t = 0.0 if n == 1 else i / (n - 1)
        
        if interpolation == "discrete":
            idx = min(int(t * num_colors), num_colors - 1)
            h, s, v = colors_hsv[idx]
        else:
            t_scaled = t * (num_colors - 1)
            idx = int(t_scaled)
            if idx >= num_colors - 1:
                h, s, v = colors_hsv[-1]
            else:
                local_t = t_scaled - idx
                c1 = colors_hsv[idx]
                c2 = colors_hsv[idx + 1]
                h = _lerp_hue_shortest(c1[0], c2[0], local_t)
                s = _lerp(c1[1], c2[1], local_t)
                v = _lerp(c1[2], c2[2], local_t)
                
        R, G, B = _hsv_to_rgb(h, s, v)
        lst.append((R, G, B))
        hex_map[i] = f"#{R:02X}{G:02X}{B:02X}"

    return lst, hex_map
