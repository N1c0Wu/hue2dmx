"""
Copyright (c) 2023 Tom Kalmijn / MIT License.
"""
import os
import glob
import subprocess
import sys
import time
from logging import Logger

from pylibftdi import Device, Driver
from typing import Optional

import threading

class DmxSender:
    def __init__(self, logger: Logger, stub_mode: bool = False, max_channel: int = 0):
        self.logger = logger
        self.stub_mode = stub_mode
        self.ftdi_serial: str = None
        self.dmx_data = bytearray(513)
        self.target_dmx_data = bytearray(513)
        self.channel_transition_time_remaining = [0.0] * 513
        self.transition_rate = 600.0  # units per second (covers 0-255 in ~425ms)
        self.universe_size = min(513, max(128, max_channel + 1))
        self._running = False
        self._thread = None
        
        if not self.stub_mode:
            self.init_ftdi_driver()
            self._start_loop()

    def init_ftdi_driver(self):
        try:
            self.ftdi_serial = self._find_ftdi_serial()
            if self.ftdi_serial:
                self.logger.info("Found FTDI port with serial %s", self.ftdi_serial)
            else:
                self.logger.warning("No FTDI device with a valid serial found initially; will retry in transmit loop")
        except Exception as e:
            self.logger.warning("Error initializing FTDI driver: %s. Will retry in transmit loop", e)

    def _find_ftdi_serial(self) -> Optional[str]:
        try:
            driver = Driver()
            devices = driver.list_devices()
            if not devices:
                return None
            for device in devices:
                manufacturer, description, serial = device
                if manufacturer == "FTDI" and serial:
                    return serial
            for device in devices:
                _, _, serial = device
                if serial:
                    return serial
        except Exception as e:
            self.logger.warning("Error listing FTDI devices: %s", e)
        return None

    def _detach_kernel_driver(self):
        """Attempts to unload ftdi_sio or unbind USB interfaces if the Linux kernel driver claimed the device."""
        try:
            subprocess.run(["sudo", "rmmod", "ftdi_sio"], capture_output=True, timeout=2)
        except Exception:
            pass

        try:
            for path in glob.glob("/sys/bus/usb/drivers/ftdi_sio/*:*"):
                dev_name = os.path.basename(path)
                try:
                    with open("/sys/bus/usb/drivers/ftdi_sio/unbind", "w") as f:
                        f.write(dev_name)
                except Exception:
                    try:
                        subprocess.run(["sudo", "sh", "-c", f"echo '{dev_name}' > /sys/bus/usb/drivers/ftdi_sio/unbind"], capture_output=True, timeout=2)
                    except Exception:
                        pass
        except Exception:
            pass

    def _open_device(self) -> Device:
        """
        Attempts to open the FTDI device.
        Tries opening with serial number first; if that fails (e.g. descriptor read race),
        falls back to opening the default/first FTDI device.
        """
        if not self.ftdi_serial:
            self.ftdi_serial = self._find_ftdi_serial()

        # 1. Attempt opening with serial if detected
        if self.ftdi_serial:
            try:
                return Device(device_id=self.ftdi_serial)
            except Exception as e:
                self.logger.warning(
                    "Could not open FTDI device with serial '%s' (%s), trying default device...",
                    self.ftdi_serial, e
                )

        # 2. Attempt opening default device (device_index=0)
        try:
            return Device()
        except Exception as e:
            # If the kernel driver is claiming the device (-5), attempt detachment
            if "-5" in str(e) or "claim" in str(e).lower():
                self.logger.info("Kernel driver conflict detected (-5). Attempting to unload ftdi_sio...")
                self._detach_kernel_driver()
                try:
                    return Device()
                except Exception:
                    pass
            # Refresh serial for subsequent attempts
            self.ftdi_serial = self._find_ftdi_serial()
            raise e

    def _start_loop(self):
        self._running = True
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()
        self.logger.info("Started DMX transmission loop.")

    def _transmit_loop(self):
        while self._running:
            ftdi_port = None
            try:
                ftdi_port = self._open_device()
                self.logger.info("DMX transmission loop successfully connected to FTDI device.")

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

                    self.send_dmx_packet(ftdi_port, self.dmx_data[:self.universe_size])
                    time.sleep(0.025)  # roughly 40Hz

            except Exception as e:
                self.logger.error("DMX transmission loop error: %s. Retrying in 2 seconds...", e)
            finally:
                if ftdi_port is not None:
                    try:
                        ftdi_port.close()
                    except Exception:
                        pass

            if self._running:
                time.sleep(2.0)

    def send_message(self, address: int, data: bytes, duration: Optional[float] = None):
        if self.stub_mode:
            # Update target and current data to keep console stub updates instant and correct
            self.target_dmx_data[address:address + len(data)] = data
            self.dmx_data[address:address + len(data)] = data
            return
        # Update target buffer! The transmit loop will smoothly interpolate towards it.
        self.target_dmx_data[address:address + len(data)] = data
        for i in range(len(data)):
            idx = address + i
            if duration and duration > 0.0:
                self.channel_transition_time_remaining[idx] = duration
            else:
                self.channel_transition_time_remaining[idx] = 0.0

    @staticmethod
    def send_dmx_packet(ftdi_port: Device, data: bytes):
        # 1. Clear any pending data in buffers before switching baudrate
        ftdi_port.flush()
        
        # 2. Switch baudrate to 9600 to prepare the Break pulse
        ftdi_port.baudrate = 9600
        ftdi_port.ftdi_fn.ftdi_set_line_property(8, 2, 0)
        
        # 3. Write a single 0x00 byte. At 9600 baud, 8N2:
        # Start bit (LOW) + 8 data bits of 0 (LOW) = 9 bits of logic LOW (~937.5 us Break).
        # Followed by 2 stop bits (HIGH) = 208.3 us logic HIGH (Mark After Break).
        ftdi_port.write(b'\x00')
        ftdi_port.flush()
        
        # 4. Sleep to let the FTDI chip fully shift out the 11 bits at 9600 baud.
        # 11 bits * (1/9600) = 1.146 milliseconds.
        # A sleep of 2.5 ms is used to ensure the Break byte has fully shifted out
        # and the line is idle before changing the baudrate back to 250000.
        time.sleep(0.0025)
        
        # 5. Switch baudrate to 250000 and send DMX data payload.
        ftdi_port.baudrate = 250000
        ftdi_port.ftdi_fn.ftdi_set_line_property(8, 2, 0)
        ftdi_port.write(bytes(data))
