from __future__ import annotations
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict
from ColorConverter import Converter, XYPoint
from palette import build_two_lamp_palette
import logging

Rgb = Tuple[int, int, int]

class PaletteConfig:
    def __init__(self, pid: str, lamp_a: str, lamp_b: str, mode: str, max_distance: int, analogous_shift_deg: float, interpolation: str = "smooth"):
        self.id = pid
        self.lamp_a = lamp_a
        self.lamp_b = lamp_b
        self.mode = mode
        self.max_distance = max_distance
        self.analogous_shift_deg = analogous_shift_deg
        self.interpolation = interpolation

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
            gamut = (
                XYPoint(light.color.gamut.red.x,   light.color.gamut.red.y),
                XYPoint(light.color.gamut.green.x, light.color.gamut.green.y),
                XYPoint(light.color.gamut.blue.x,  light.color.gamut.blue.y),
            )
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
            b = self._lamp_rgb.get(cfg.lamp_b)
            if a is None or b is None:
                continue
            lst, hex_map = build_two_lamp_palette(
                a, b, mode=cfg.mode, max_distance=cfg.max_distance, analogous_shift_deg=cfg.analogous_shift_deg, interpolation=cfg.interpolation
            )
            self._palette_rgb_list[pid] = lst
            self._palette_hex_map[pid] = hex_map
        return list(impacted)

    def get_color_for(self, palette_id: str, distance: int) -> Rgb:
        cfg = self._palettes[palette_id]
        lst = self._palette_rgb_list.get(palette_id)
        if not lst:
            return (0, 0, 0)  # vor dem ersten Event: Schwarz
        i = max(0, min(cfg.max_distance - 1, int(distance)))
        return lst[i]

    def fixtures_for(self, palette_id: str):
        return self._palette_to_fixtures.get(palette_id, [])

    def hex_map_for(self, palette_id: str) -> Dict[int, str]:
        return self._palette_hex_map.get(palette_id, {})
