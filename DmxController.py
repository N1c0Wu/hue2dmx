import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
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
from HueModel import Point, Color, Dimming, On, Effects, Dynamics, ColorTemperature


class DmxController:
    DEBOUNCE_DELAY = 0.2  # 200 milliseconds debounce delay
    MAX_CONCURRENT_UPDATES = 5  # Limit to 5 simultaneous updates

    def __init__(self):
        self.running_as_service = os.getenv('RUNNING_AS_SERVICE', 'false').lower() == 'true'
        self._load_env()
        # Re-evaluate RUNNING_AS_SERVICE in case it was loaded from the env file
        self.running_as_service = os.getenv('RUNNING_AS_SERVICE', 'false').lower() == 'true'
        self.logger = self._init_logger()
        self.dmx_fixtures: List[DmxFixture] = []
        self.dmx_sender: Optional[DmxSender] = None
        self.hue_bridge: Optional[HueBridge] = None

        self.update_queue = collections.deque()  # FIFO queue for updates
        self.update_lock = threading.Lock()
        self.semaphore = threading.Semaphore(self.MAX_CONCURRENT_UPDATES)  # Limit concurrency

        self._active_transitions = {}
        self._transitions_lock = threading.Lock()

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

        # Prevent duplicate handlers if _init_logger is called multiple times
        if not logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            logger.addHandler(console_handler)

            try:
                file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
                file_handler.setLevel(logging.INFO)
                file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
                logger.addHandler(file_handler)
            except Exception as e:
                # Fall back to console only if file is not writeable (e.g. permission issues in background service)
                print(f"Warning: Could not initialize file log handler ({log_file}): {e}", file=sys.stderr)

        return logger

    def _initialize(self):
        """Initializes DMX fixtures, DMX sender, and the Hue bridge connection."""
        self.logger.info("Loading DMX fixtures")
        self.dmx_fixtures = self._load_dmx_fixtures()

        max_channel = 0
        for fx in self.dmx_fixtures:
            limit = fx.dmx_address + getattr(fx, "_length", 1) - 1
            if limit > max_channel:
                max_channel = limit
        self.logger.info(f"Max configured DMX channel is {max_channel}")

        self.logger.info("Initializing DMX sender")
        self.test_mode = os.getenv('STUB_DMX', 'false').lower() == 'true'
        self.dmx_sender = DmxSender(logger=self.logger, stub_mode=self.test_mode, max_channel=max_channel)

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
        if not yaml_path:
            # Fallback to fixtures.yml in the script directory, then current working directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            yaml_path = os.path.join(script_dir, "fixtures.yml")
            if not os.path.exists(yaml_path):
                yaml_path = os.path.join(os.getcwd(), "fixtures.yml")

        if not (yaml_path and os.path.exists(yaml_path)):
            self.logger.warning(f"Fixtures YAML file not found at: {yaml_path}")
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
        self.logger.error("No fixtures YAML loaded. Make sure fixtures.yml exists in the script directory or FIXTURES_YAML is set to a valid path.")
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
            light = self.hue_bridge.get_light(hue_id)
            if light.color_temperature and getattr(light.color_temperature, "mirek", None) is not None:
                light._color_mode = "color_temperature"
            else:
                light._color_mode = "color"
            self._cached_lights[hue_id] = light



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
                            light._color_mode = "color"
                            if light.color and light.color.xy:
                                light.color.xy.x = item["color"]["xy"].get("x", light.color.xy.x)
                                light.color.xy.y = item["color"]["xy"].get("y", light.color.xy.y)
                                updated = True
                            elif not light.color:
                                light.color = Color(xy=Point(x=item["color"]["xy"].get("x", 0.0), y=item["color"]["xy"].get("y", 0.0)))
                                updated = True
                        if "color_temperature" in item and "mirek" in item["color_temperature"]:
                            light._color_mode = "color_temperature"
                            if light.color_temperature:
                                light.color_temperature.mirek = item["color_temperature"].get("mirek", light.color_temperature.mirek)
                                updated = True
                            elif not light.color_temperature:
                                light.color_temperature = ColorTemperature(mirek=item["color_temperature"].get("mirek"))
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
                        if "effects" in item and "status" in item["effects"]:
                            if light.effects:
                                light.effects.status = item["effects"].get("status", light.effects.status)
                                updated = True
                            elif not light.effects:
                                light.effects = Effects(status=item["effects"].get("status", "no_effect"), status_values=[], effect_values=[])
                                updated = True
                        if "dynamics" in item:
                            if light.dynamics:
                                light.dynamics.status = item["dynamics"].get("status", light.dynamics.status)
                                light.dynamics.speed = item["dynamics"].get("speed", light.dynamics.speed)
                                if "duration" in item["dynamics"]:
                                    light.dynamics.duration = item["dynamics"]["duration"]
                                updated = True
                            elif not light.dynamics:
                                light.dynamics = Dynamics(
                                    status=item["dynamics"].get("status", "none"),
                                    status_values=[],
                                    speed=item["dynamics"].get("speed", 0.0),
                                    speed_valid=False,
                                    duration=item["dynamics"].get("duration")
                                )
                                updated = True
                        
                        if updated:
                            try:
                                self._handle_hue_light_event(light)
                            except Exception as e:
                                self.logger.warning("Failed to handle event for %s: %s", lid, e)

            time.sleep(60)  # Retry connection every minute if disconnected

    def _send_dmx(self, address: int, payload: bytes, name: str = "", log_update: bool = True, duration: Optional[float] = None):
        if self.test_mode:
            if log_update:
                channels_str = ", ".join(f"[{address + i}]: {val}" for i, val in enumerate(payload))
                self.logger.info(f"Update {name} -> {channels_str} (duration: {duration}s)")
        else:
            self.dmx_sender.send_message(address, payload, duration=duration)

    def _start_animation_loop(self):
        self.logger.info("Starting DMX palette animation loop...")
        threading.Thread(target=self._run_animation, daemon=True).start()

    def _run_animation(self):
        while True:
            try:
                now = time.time()
                for fx in self.dmx_fixtures:
                    if type(fx).__name__ == "YamlRgbFixture":
                        cfg = self.palette_mgr._palettes.get(fx.palette_id)
                        if cfg:
                            # Default speed from config
                            speed = getattr(cfg, "speed", 0.0)
                            
                            # Check if the primary lamp of this palette is in any active effect or dynamic palette mode
                            is_animating = False
                            lamp_speed = 0.0
                            for lamp_id in [cfg.lamp_a, cfg.lamp_b]:
                                if lamp_id:
                                    lamp_light = self._cached_lights.get(lamp_id)
                                    if lamp_light:
                                        eff = getattr(lamp_light.effects, "status", "no_effect") if lamp_light.effects else "no_effect"
                                        dyn = getattr(lamp_light.dynamics, "status", "none") if lamp_light.dynamics else "none"
                                        if eff != "no_effect" or dyn == "dynamic_palette":
                                            is_animating = True
                                            if lamp_light.dynamics and getattr(lamp_light.dynamics, "speed", 0.0) > 0.0:
                                                lamp_speed = lamp_light.dynamics.speed
                                            break
                                        
                            if is_animating:
                                # Run a default animation speed (e.g. 0.5) if speed is 0
                                speed = lamp_speed if lamp_speed > 0.0 else (speed if speed > 0.0 else 0.5)
                                
                            if speed > 0.0:
                                # Scale speed by max_distance so cycle duration is consistent
                                # A speed of 1.0 means a full cycle (max_distance steps) takes ~10 seconds.
                                total_steps = getattr(cfg, "max_distance", 100)
                                step_speed = speed * (total_steps / 10.0)
                                offset = now * step_speed
                                payload = fx.get_dmx_message(offset=offset)
                                self._send_dmx(fx.dmx_address, payload, fx.name, log_update=False)
            except Exception as e:
                self.logger.error("Error in animation loop: %s", e)
            time.sleep(0.04)  # ~25 FPS

    def _handle_hue_light_event(self, light):
        duration = None
        if light.dynamics and getattr(light.dynamics, "duration", None) is not None:
            duration = light.dynamics.duration / 1000.0
            # Reset duration on the model so it only applies once
            light.dynamics.duration = None

        if hasattr(self, "palette_mgr") and getattr(self, "palette_mgr", None):
            lid = light.id
            impacted = list(self.palette_mgr._lamp_to_palette_ids.get(lid, set()))
            
            if duration and duration > 0.0:
                for pid in impacted:
                    cfg = self.palette_mgr._palettes.get(pid)
                    if not cfg:
                        continue
                    old_a = self.palette_mgr._lamp_rgb.get(cfg.lamp_a)
                    old_b = self.palette_mgr._lamp_rgb.get(cfg.lamp_b)
                    
                    target_color = self.palette_mgr._xy_to_rgb(light)
                    if target_color is None:
                        continue
                        
                    target_a = target_color if cfg.lamp_a == lid else old_a
                    target_b = target_color if cfg.lamp_b == lid else old_b
                    
                    if old_a is None or old_b is None or target_a is None or target_b is None:
                        self.palette_mgr.update_from_hue_event(light)
                        for fx in self.palette_mgr.fixtures_for(pid):
                            payload = fx.get_dmx_message()
                            self._send_dmx(fx.dmx_address, payload, fx.name)
                        continue
                        
                    with self._transitions_lock:
                        old_cancel = self._active_transitions.get(pid)
                        if old_cancel:
                            old_cancel.set()
                        cancel_event = threading.Event()
                        self._active_transitions[pid] = cancel_event
                        
                    threading.Thread(
                        target=self._run_palette_transition,
                        args=(pid, old_a, old_b, target_a, target_b, duration, cancel_event),
                        daemon=True
                    ).start()
            else:
                impacted_pids = self.palette_mgr.update_from_hue_event(light)
                for pid in impacted_pids:
                    with self._transitions_lock:
                        old_cancel = self._active_transitions.get(pid)
                        if old_cancel:
                            old_cancel.set()
                            self._active_transitions.pop(pid, None)
                    for fx in self.palette_mgr.fixtures_for(pid):
                        payload = fx.get_dmx_message()
                        self._send_dmx(fx.dmx_address, payload, fx.name)

    def _run_palette_transition(self, pid, old_a, old_b, target_a, target_b, duration, cancel_event):
        self.logger.info(f"Starting wave transition for palette {pid} over {duration}s")
        start_time = time.time()
        cfg = self.palette_mgr._palettes[pid]
        max_distance = getattr(cfg, "max_distance", 100)
        
        while not cancel_event.is_set():
            now = time.time()
            elapsed = now - start_time
            t = elapsed / duration
            if t >= 1.0:
                t = 1.0
                
            current_a = self.palette_mgr.interpolate_rgb(old_a, target_a, t)
            current_b = self.palette_mgr.interpolate_rgb(old_b, target_b, t)
            
            self.palette_mgr.update_palette_intermediate(pid, current_a, current_b)
            
            is_cyclic = cfg.mode in ("triadic", "tetradic", "split_complementary", "to_complement")
            period = max_distance if is_cyclic else (2 * max_distance - 2)
            if period <= 0:
                period = 1
            offset = t * period
            
            for fx in self.palette_mgr.fixtures_for(pid):
                payload = fx.get_dmx_message(offset=offset)
                self._send_dmx(fx.dmx_address, payload, fx.name, log_update=False, duration=None)
                
            if t >= 1.0:
                break
                
            time.sleep(0.04) # ~25 FPS
            
        if not cancel_event.is_set():
            self.palette_mgr.update_palette_intermediate(pid, target_a, target_b)
            for fx in self.palette_mgr.fixtures_for(pid):
                payload = fx.get_dmx_message(offset=0.0)
                self._send_dmx(fx.dmx_address, payload, fx.name, log_update=False, duration=None)
            self.logger.info(f"Wave transition for palette {pid} completed successfully.")
            
            with self._transitions_lock:
                if self._active_transitions.get(pid) == cancel_event:
                    self._active_transitions.pop(pid, None)

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
