from __future__ import annotations
from typing import Dict, List
from DmxFixture import DmxFixture
from PaletteManager import PaletteManager

class YamlRgbFixture(DmxFixture):
    """
    RGB-Fixture mit:
      - channels: { r, g, b } (absolute DMX-Kanäle)
      - steady: { "<abs_channel>": val } (optional)
      - distance: Index in die Palette (0..max_distance-1)
    """
    def __init__(self, name: str, palette_id: str, channels: Dict[str, int],
                 distance: int, steady: Dict[str, int] | None, palette_mgr: PaletteManager):
        used = [int(channels['r']), int(channels['g']), int(channels['b'])]
        if steady:
            used += [int(k) for k in steady.keys()]
        start, end = min(used), max(used)
        super().__init__(name=name, hue_light_id="__palette__", dmx_address=start)
        self._length = end - start + 1
        self._r_off = int(channels['r']) - start
        self._g_off = int(channels['g']) - start
        self._b_off = int(channels['b']) - start
        self._steady = {int(k) - start: int(v) for k, v in (steady or {}).items()}
        self.distance = int(distance)
        self.palette_id = palette_id
        self.palette_mgr = palette_mgr

    def get_dmx_message(self, offset: float = 0.0) -> bytes:
        R, G, B = self.palette_mgr.get_color_for(self.palette_id, self.distance, offset=offset)
        frame: List[int] = [0] * self._length
        frame[self._r_off] = R; frame[self._g_off] = G; frame[self._b_off] = B
        for off, val in self._steady.items():
            if 0 <= off < self._length:
                frame[off] = val
        return bytes(frame)
