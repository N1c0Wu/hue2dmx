import json
import logging
import os
import threading
import time
import collections
import yaml
from typing import List, Optional
from dotenv import load_dotenv

from DmxFixture import DmxFixture
from DmxSender import DmxSender
from HueBridge import HueBridge
from PaletteManager import PaletteManager, PaletteConfig
from YamlRgbFixture import YamlRgbFixture
from YamlSteadyFixture import YamlSteadyFixture
from HueModel import Point, Color, Dimming, On


class DmxController:
    DEBOUNCE_DELAY = 0.2  # 200 milliseconds debounce delay
    MAX_CONCURRENT_UPDATES = 5  # Limit to 5 simultaneous updates

    def __init__(self):
        self.running_as_service = os.getenv('RUNNING_AS_SERVICE', 'false').lower() == 'true'
        self._load_env()
        self.logger = self._init_logger()
        self.dmx_fixtures: List[DmxFixture] = []
        self.dmx_sender: Optional[DmxSender] = None
        self.hue_bridge: Optional[HueBridge] = None

        self.update_queue = collections.deque()  # FIFO queue for updates
        self.update_lock = threading.Lock()
        self.semaphore = threading.Semaphore(self.MAX_CONCURRENT_UPDATES)  # Limit concurrency

        self._initialize()

    def _load_env(self):
        """Loads environment variables from the appropriate `.env` file."""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        dotenv_path = os.path.join(script_dir, 'config-service.env' if self.running_as_service else 'config-console.env')
        load_dotenv(dotenv_path=dotenv_path)

    @staticmethod
    def _init_logger():
        """Initializes and returns the logger."""
        logger = logging.getLogger("DmxController")
        logger.setLevel(logging.INFO)
        log_file = os.getenv('LOG_FILE', 'dmx_controller.log')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        return logger

    def _initialize(self):
        """Initializes DMX fixtures, DMX sender, and the Hue bridge connection."""
        self.logger.info("Loading DMX fixtures")
        self.dmx_fixtures = self._load_dmx_fixtures()

        self.logger.info("Initializing DMX sender")
        self.test_mode = os.getenv('STUB_DMX', 'false').lower() == 'true'
        self.dmx_sender = DmxSender(logger=self.logger, stub_mode=self.test_mode)

        self.logger.info("Connecting to Hue bridge")
        self.hue_bridge = HueBridge(
            bridge_ip=os.getenv('HUE_BRIDGE_IP'),
            api_key=os.getenv('HUE_API_KEY'),
            timeout_sec=int(os.getenv('HUE_TIMEOUT_SEC', 240)),
            logger=self.logger
        )
        self._validate_fixtures()
        self._start_animation_loop()

    def _load_from_yaml(self):
        yaml_path = os.getenv("FIXTURES_YAML")
        if not (yaml_path and os.path.exists(yaml_path)):
            return None
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        hue_cfg = cfg.get("hue") or {}
        if "bridge_ip" in hue_cfg:
            os.environ["HUE_BRIDGE_IP"] = str(hue_cfg["bridge_ip"])
        if "api_key" in hue_cfg:
            os.environ["HUE_API_KEY"] = str(hue_cfg["api_key"])
        if "timeout_sec" in hue_cfg:
            os.environ["HUE_TIMEOUT_SEC"] = str(hue_cfg["timeout_sec"])
        
        dmx_cfg = cfg.get("dmx") or {}
        if "stub" in dmx_cfg:
            os.environ["STUB_DMX"] = "true" if dmx_cfg["stub"] else "false"

        pm = PaletteManager(self.logger)

        for p in (cfg.get("palettes") or []):
            pm.register_palette(PaletteConfig(
                pid=p["id"],
                lamp_a=p["hue_light_ids"][0],
                lamp_b=p["hue_light_ids"][1],
                mode=str(p.get("mode", "blend")).lower(),
                max_distance=int(p.get("max_distance", 100)),
                analogous_shift_deg=float(p.get("analogous_shift_deg", 20.0)),
                interpolation=str(p.get("interpolation", "smooth")).lower(),
                speed=float(p.get("speed", 0.0))
            ))

        fixtures = []
        for entry in (cfg.get("fixtures") or []):
            if entry["type"] == "rgb":
                fx = YamlRgbFixture(
                    name=entry["name"],
                    palette_id=entry["palette"],
                    channels=entry["channels"],
                    distance=int(entry.get("distance", 0)),
                    steady=entry.get("steady"),
                    palette_mgr=pm,
                )
                pm.register_fixture(entry["palette"], fx)
                fixtures.append(fx)
            elif entry["type"] == "steady":
                fx = YamlSteadyFixture(name=entry["name"], channels=entry["channels"])
                fixtures.append(fx)
            else:
                self.logger.warning(f"Unknown fixture type: {entry['type']}")

        self.palette_mgr = pm
        return fixtures

    def _load_dmx_fixtures(self) -> List[DmxFixture]:
        yaml_fixtures = self._load_from_yaml()
        if yaml_fixtures is not None:
            return yaml_fixtures
        self.logger.error("No fixtures YAML loaded. Make sure FIXTURES_YAML is set.")
        exit(1)

    def send_heartbeat(self):
        """Sends periodic updates to the Hue bridge to prevent timeouts."""
        def heartbeat():
            while True:
                try:
                    if hasattr(self, "palette_mgr") and getattr(self, "palette_mgr", None) and self.palette_mgr._lamp_to_palette_ids:
                        hue_id = list(self.palette_mgr._lamp_to_palette_ids.keys())[0]
                    else:
                        self.logger.warning("No Hue ID specified for heartbeat.")
                        return

                    hue_light = self.hue_bridge.get_light(hue_id)
                    function = "unknown" if hue_light.metadata.function == "mixed" else "mixed"
                    self.hue_bridge.set_light_state(hue_id, {"metadata": {"function": function}})
                except Exception as e:
                    self.logger.error("Error sending heartbeat to Hue bridge: %s", e)

                time.sleep(180)  # Every 3 minutes

        threading.Thread(target=heartbeat, daemon=True).start()

    def _validate_fixtures(self):
        """Validates that all mapped Hue lights exist in the Hue bridge."""
        if not hasattr(self, "palette_mgr") or not self.palette_mgr:
            return
            
        hue_bulbs = self.hue_bridge.list_light_ids_and_names()
        self._cached_lights = {}
        for hue_id in self.palette_mgr._lamp_to_palette_ids.keys():
            if not hue_id:  # skip empty ids
                continue
            if hue_id not in hue_bulbs:
                self.logger.error(f"Hue ID '{hue_id}' specified in your palettes cannot be found on the bridge.")
                self.logger.info("Valid IDs:")
                for key, value in hue_bulbs.items():
                    self.logger.info(f"    {key}: {value}")
                exit(1)
            
            # Cache the initial full state so we don't need to do HTTP GETs later
            self.logger.info(f"Caching initial state for Hue light: {hue_id}")
            self._cached_lights[hue_id] = self.hue_bridge.get_light(hue_id)



    def track_and_update_fixtures(self):
        """Listens for Hue bridge events and synchronizes updates with DMX fixtures."""
        self.logger.info("Start listening for Hue bridge events...")
        while True:
            for event in self.hue_bridge.event_stream():
                if event["type"] == "update":
                    if not self.running_as_service:
                        self.logger.info(json.dumps(event, indent=4))
                    
                    if self._contains_button_short_release(event):
                        self.logger.info("Button short release detected. Refreshing cache and syncing all lights...")
                        for lid in self.palette_mgr._lamp_to_palette_ids.keys():
                            if not lid:
                                continue
                            try:
                                light = self.hue_bridge.get_light(lid)
                                self._cached_lights[lid] = light
                                self._handle_hue_light_event(light)
                            except Exception as e:
                                self.logger.warning("Failed to refresh state for %s: %s", lid, e)
                        continue

                    # Process updates by applying deltas locally to cached models
                    for item in event.get("data", []):
                        lid = item.get("id")
                        if not lid or lid not in self.palette_mgr._lamp_to_palette_ids:
                            continue
                        
                        light = self._cached_lights.get(lid)
                        if not light:
                            continue
                        
                        # Apply deltas from the SSE event directly to our cached light model
                        updated = False
                        if "color" in item and "xy" in item["color"]:
                            if light.color and light.color.xy:
                                light.color.xy.x = item["color"]["xy"].get("x", light.color.xy.x)
                                light.color.xy.y = item["color"]["xy"].get("y", light.color.xy.y)
                                updated = True
                            elif not light.color:
                                light.color = Color(xy=Point(x=item["color"]["xy"].get("x", 0.0), y=item["color"]["xy"].get("y", 0.0)))
                                updated = True
                        if "dimming" in item and "brightness" in item["dimming"]:
                            if light.dimming:
                                light.dimming.brightness = item["dimming"].get("brightness", light.dimming.brightness)
                                updated = True
                            elif not light.dimming:
                                light.dimming = Dimming(brightness=item["dimming"].get("brightness", 100.0))
                                updated = True
                        if "on" in item and "on" in item["on"]:
                            if light.on:
                                light.on.on = item["on"].get("on", light.on.on)
                                updated = True
                            elif not light.on:
                                light.on = On(on=item["on"].get("on", False))
                                updated = True
                        
                        if updated:
                            try:
                                self._handle_hue_light_event(light)
                            except Exception as e:
                                self.logger.warning("Failed to handle event for %s: %s", lid, e)

            time.sleep(60)  # Retry connection every minute if disconnected

    def _send_dmx(self, address: int, payload: bytes, name: str = "", log_update: bool = True):
        if self.test_mode:
            if log_update:
                channels_str = ", ".join(f"[{address + i}]: {val}" for i, val in enumerate(payload))
                self.logger.info(f"Update {name} -> {channels_str}")
        else:
            self.dmx_sender.send_message(address, payload)

    def _start_animation_loop(self):
        has_animation = False
        if hasattr(self, "palette_mgr") and self.palette_mgr:
            for cfg in self.palette_mgr._palettes.values():
                if getattr(cfg, "speed", 0.0) > 0.0:
                    has_animation = True
                    break
        
        if has_animation:
            self.logger.info("Starting DMX palette animation loop...")
            threading.Thread(target=self._run_animation, daemon=True).start()

    def _run_animation(self):
        while True:
            try:
                now = time.time()
                for fx in self.dmx_fixtures:
                    if type(fx).__name__ == "YamlRgbFixture":
                        cfg = self.palette_mgr._palettes.get(fx.palette_id)
                        if cfg and getattr(cfg, "speed", 0.0) > 0.0:
                            offset = now * cfg.speed
                            payload = fx.get_dmx_message(offset=offset)
                            self._send_dmx(fx.dmx_address, payload, fx.name, log_update=False)
            except Exception as e:
                self.logger.error("Error in animation loop: %s", e)
            time.sleep(0.04)  # ~25 FPS

    def _handle_hue_light_event(self, light):
        if hasattr(self, "palette_mgr") and getattr(self, "palette_mgr", None):
            impacted = self.palette_mgr.update_from_hue_event(light)
            for pid in impacted:
                for fx in self.palette_mgr.fixtures_for(pid):
                    payload = fx.get_dmx_message()
                    self._send_dmx(fx.dmx_address, payload, fx.name)

    @staticmethod
    def _contains_button_short_release(event: dict) -> bool:
        """Checks if a Hue event contains a button short release."""
        if "data" not in event:
            return False

        for item in event["data"]:
            if item.get("type") == "button":
                button = item.get("button", {})
                if button.get("last_event") == "short_release":
                    return True
        return False

    def _force_initial_dmx(self):
        self.logger.info("Sending initial DMX states...")
        # Force update for all cached Hue lights
        for lid, light in self._cached_lights.items():
            try:
                self._handle_hue_light_event(light)
            except Exception as e:
                self.logger.warning("Initial update failed for %s: %s", lid, e)
                
        # Force update for steady fixtures
        for fx in self.dmx_fixtures:
            if type(fx).__name__ == "YamlSteadyFixture":
                payload = fx.get_dmx_message()
                self._send_dmx(fx.dmx_address, payload, fx.name)

if __name__ == "__main__":
    controller = DmxController()
    controller.send_heartbeat()  # Start sending heartbeat updates
    controller._force_initial_dmx()  # Set initial DMX outputs before listening
    controller.track_and_update_fixtures()  # Start listening for updates
