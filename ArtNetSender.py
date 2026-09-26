import sys
import time
import socket
import struct
import threading
from logging import Logger
from typing import Optional

class ArtNetSender:
    def __init__(self, logger: Logger, ip: str = "127.0.0.1", port: int = 6454,
                 start_universe: int = 0, max_channel: int = 0):
        self.logger = logger
        self.ip = ip
        self.port = port
        self.start_universe = start_universe
        
        self.universe_count = max(1, (max_channel + 511) // 512)
        self.total_buffer_size = self.universe_count * 512 + 1
        
        self.dmx_data = bytearray(self.total_buffer_size)
        self.target_dmx_data = bytearray(self.total_buffer_size)
        self.channel_transition_time_remaining = [0.0] * self.total_buffer_size
        self.transition_rate = 600.0  # units per second (covers 0-255 in ~425ms)
        
        self._running = False
        self._thread = None
        self.sock = None
        
        self.init_socket()
        self._start_loop()

    def init_socket(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.logger.info(f"Initialized Art-Net sender socket targeting {self.ip}:{self.port}")
        except Exception as e:
            self.logger.error("Error initializing Art-Net socket: %s", e)
            sys.exit(1)

    def _start_loop(self):
        self._running = True
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()
        self.logger.info("Started Art-Net transmission loop.")

    def _transmit_loop(self):
        while self._running:
            try:
                # Initialize current state to match target state to avoid fading in on startup
                self.dmx_data = bytearray(self.target_dmx_data)
                
                last_time = time.time()
                while self._running:
                    now = time.time()
                    dt = now - last_time
                    last_time = now
                    
                    # Interpolate current values towards targets
                    for i in range(len(self.dmx_data)):
                        cur = self.dmx_data[i]
                        tar = self.target_dmx_data[i]
                        if cur != tar:
                            rem_time = self.channel_transition_time_remaining[i]
                            if rem_time > 0.0:
                                if dt >= rem_time:
                                    self.dmx_data[i] = tar
                                    self.channel_transition_time_remaining[i] = 0.0
                                else:
                                    diff = tar - cur
                                    step = diff * (dt / rem_time)
                                    new_val = cur + step
                                    if diff > 0:
                                        self.dmx_data[i] = min(tar, max(cur + 1, int(new_val)))
                                    else:
                                        self.dmx_data[i] = max(tar, min(cur - 1, int(new_val)))
                                    self.channel_transition_time_remaining[i] = rem_time - dt
                            else:
                                rate = self.transition_rate * dt
                                diff = tar - cur
                                if abs(diff) <= rate:
                                    self.dmx_data[i] = tar
                                else:
                                    if diff > 0:
                                        self.dmx_data[i] = int(cur + rate)
                                    else:
                                        self.dmx_data[i] = int(cur - rate)
                                    
                    for u in range(self.universe_count):
                        start_idx = u * 512 + 1
                        end_idx = start_idx + 512
                        dmx_slice = self.dmx_data[start_idx:end_idx]
                        
                        # Art-Net Header
                        header = b'Art-Net\x00' + struct.pack('<H', 0x5000) + struct.pack('>H', 14)
                        universe = self.start_universe + u
                        packet = header + b'\x00\x00' + struct.pack('>H', universe) + struct.pack('>H', 512) + bytes(dmx_slice)
                        
                        try:
                            self.sock.sendto(packet, (self.ip, self.port))
                        except Exception as e:
                            self.logger.error("Error sending Art-Net packet: %s", e)
                            
                    time.sleep(0.025)  # roughly 40Hz
            except Exception as e:
                self.logger.error("Art-Net transmit loop error: %s. Retrying in 2 seconds...", e)
                if self._running:
                    time.sleep(2.0)

    def send_message(self, address: int, data: bytes, duration: Optional[float] = None):
        # Update target buffer! The transmit loop will smoothly interpolate towards it.
        self.target_dmx_data[address:address + len(data)] = data
        for i in range(len(data)):
            idx = address + i
            if duration and duration > 0.0:
                self.channel_transition_time_remaining[idx] = duration
            else:
                self.channel_transition_time_remaining[idx] = 0.0
