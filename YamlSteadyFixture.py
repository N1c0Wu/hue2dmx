from typing import Dict, List
from DmxFixture import DmxFixture

class YamlSteadyFixture(DmxFixture):
    def __init__(self, name: str, channels: Dict[str, int]):
        used = [int(k) for k in channels.keys()]
        start, end = min(used), max(used)
        super().__init__(name=name, hue_light_id="__steady__", dmx_address=start)
        self._length = end - start + 1
        frame: List[int] = [0] * self._length
        for abs_ch, val in channels.items():
            frame[int(abs_ch) - start] = int(val)
        self._payload = bytes(frame)

    def get_dmx_message(self, offset: float = 0.0) -> bytes:
        return self._payload
