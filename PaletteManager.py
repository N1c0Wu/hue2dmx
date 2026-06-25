from __future__ import annotations
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict
from ColorConverter import Converter, XYPoint, GamutA, GamutB, GamutC
from palette import build_two_lamp_palette, _rgb_to_hsv, _hsv_to_rgb, _lerp_hue_shortest, _lerp
from kelvin_rgb import kelvin_table
import logging

Rgb = Tuple[int, int, int]

class PaletteConfig:
    def __init__(self, pid: str, lamp_a: str, lamp_b: str, mode: str, max_distance: int, analogous_shift_deg: float, interpolation: str = "smooth", speed: float = 0.0):
        self.id = pid
        self.lamp_a = lamp_a
        self.lamp_b = lamp_b
        self.mode = mode
        self.max_distance = max_distance
        self.analogous_shift_deg = analogous_shift_deg
        self.interpolation = interpolation
        self.speed = speed

class PaletteManager:
    """
    - cached RGB pro Hue-Lampe
    - Palette je id: berechnete Liste (0..N-1) + Hex-Map
    - Zuordnung Palette → Fixtures
    """
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.log = logger or logging.getLogger(__name__)
        self._lamp_rgb: Dict[str, Rgb] = {}
        self._palettes: Dict[str, PaletteConfig] = {}
        self._palette_rgb_list: Dict[str, List[Rgb]] = {}
        self._palette_hex_map: Dict[str, Dict[int, str]] = {}
        self._lamp_to_palette_ids: Dict[str, Set[str]] = defaultdict(set)
        self._palette_to_fixtures: Dict[str, List[object]] = defaultdict(list)

    def register_palette(self, cfg: PaletteConfig):
        self._palettes[cfg.id] = cfg
        self._lamp_to_palette_ids[cfg.lamp_a].add(cfg.id)
        self._lamp_to_palette_ids[cfg.lamp_b].add(cfg.id)

    def register_fixture(self, palette_id: str, fx: object):
        self._palette_to_fixtures[palette_id].append(fx)

    def _xy_to_rgb(self, light) -> Optional[Rgb]:
        try:
            if not light.on.on:
                return (0, 0, 0)
            
            color_mode = getattr(light, "_color_mode", "color")
            if color_mode == "color_temperature" and light.color_temperature and light.color_temperature.mirek is not None:
                mirek = light.color_temperature.mirek
                kelvin = 1000000.0 / mirek
                closest_kelvin = min(kelvin_table.keys(), key=lambda k: abs(k - kelvin))
                r, g, b = kelvin_table[closest_kelvin]
            else:
                if not light.color:
                    # Fallback to white if color object is missing
                    r, g, b = (255, 255, 255)
                else:
                    if light.color.gamut:
                        gamut = (
                            XYPoint(light.color.gamut.red.x,   light.color.gamut.red.y),
                            XYPoint(light.color.gamut.green.x, light.color.gamut.green.y),
                            XYPoint(light.color.gamut.blue.x,  light.color.gamut.blue.y),
                        )
                    else:
                        gt = getattr(light.color, "gamut_type", "B")
                        if gt == "A":
                            gamut = GamutA
                        elif gt == "C":
                            gamut = GamutC
                        else:
                            gamut = GamutB
                    
                    x, y = light.color.xy.x, light.color.xy.y
                    r, g, b = Converter(gamut).xy_to_rgb(x, y)
                    
            dim = float(getattr(light.dimming, "brightness", 100.0)) / 100.0
            return (max(0,min(255,int(r*dim))),
                    max(0,min(255,int(g*dim))),
                    max(0,min(255,int(b*dim))))
        except Exception as e:
            self.log.warning("xy->rgb failure: %s", e)
            return None

    def update_from_hue_event(self, light) -> List[str]:
        """Aktualisiert die betroffenen Paletten. Rückgabe: Liste Palette-IDs."""
        lid = light.id
        rgb = self._xy_to_rgb(light)
        if rgb is None:
            return []
        self._lamp_rgb[lid] = rgb
        impacted = set(self._lamp_to_palette_ids.get(lid, set()))
        for pid in impacted:
            cfg = self._palettes[pid]
            a = self._lamp_rgb.get(cfg.lamp_a)
            if a is None:
                continue
                
            if cfg.mode in ("blend", "complementary", "analogous"):
                b = self._lamp_rgb.get(cfg.lamp_b)
                if b is None:
                    continue
            else:
                b = (0, 0, 0)
            lst, hex_map = build_two_lamp_palette(
                a, b, mode=cfg.mode, max_distance=cfg.max_distance, analogous_shift_deg=cfg.analogous_shift_deg, interpolation=cfg.interpolation
            )
            self._palette_rgb_list[pid] = lst
            self._palette_hex_map[pid] = hex_map
            self.log.info("Updated palette %s using Lamp A (RGB: %s) and Lamp B (RGB: %s) [Mode: %s]", pid, a, b, cfg.mode)
        return list(impacted)

    def get_color_for(self, palette_id: str, distance: int, offset: float = 0.0) -> Rgb:
        cfg = self._palettes[palette_id]
        lst = self._palette_rgb_list.get(palette_id)
        if not lst:
            return (0, 0, 0)  # vor dem ersten Event: Schwarz
            
        total_steps = cfg.max_distance
        raw_idx = distance + offset
        
        # Algorithmic modes are cyclic (hue wraps around 0-360 degrees).
        # Linear modes like blend shift from A -> B. Ping-pong them to avoid hard color jumps.
        is_cyclic = cfg.mode in ("triadic", "tetradic", "split_complementary", "to_complement")
        
        if is_cyclic:
            i = int(round(raw_idx)) % total_steps
        else:
            period = 2 * total_steps - 2
            if period <= 0:
                i = 0
            else:
                idx = int(round(raw_idx)) % period
                if idx >= total_steps:
                    i = period - idx
                else:
                    i = idx
                    
        i = max(0, min(total_steps - 1, i))
        return lst[i]

    def fixtures_for(self, palette_id: str):
        return self._palette_to_fixtures.get(palette_id, [])

    def hex_map_for(self, palette_id: str) -> Dict[int, str]:
        return self._palette_hex_map.get(palette_id, {})

    def interpolate_rgb(self, rgb_start: Rgb, rgb_end: Rgb, t: float) -> Rgb:
        h1, s1, v1 = _rgb_to_hsv(rgb_start)
        h2, s2, v2 = _rgb_to_hsv(rgb_end)
        
        h = _lerp_hue_shortest(h1, h2, t)
        s = _lerp(s1, s2, t)
        v = _lerp(v1, v2, t)
        
        return _hsv_to_rgb(h, s, v)

    def update_palette_intermediate(self, pid: str, rgb_a: Rgb, rgb_b: Rgb):
        cfg = self._palettes[pid]
        self._lamp_rgb[cfg.lamp_a] = rgb_a
        self._lamp_rgb[cfg.lamp_b] = rgb_b
        lst, hex_map = build_two_lamp_palette(
            rgb_a, rgb_b, mode=cfg.mode, max_distance=cfg.max_distance, analogous_shift_deg=cfg.analogous_shift_deg, interpolation=cfg.interpolation
        )
        self._palette_rgb_list[pid] = lst
        self._palette_hex_map[pid] = hex_map
