"""
Copyright (c) 2023 Tom Kalmijn / MIT License.
"""
import sys
import time
from logging import Logger

from pylibftdi import Device, Driver


import threading

class DmxSender:
    def __init__(self, logger: Logger, stub_mode: bool = False):
        self.logger = logger
        self.stub_mode = stub_mode
        self.ftdi_serial: str = None
        self.dmx_data = bytearray(513)
        self._running = False
        self._thread = None
        
        if not self.stub_mode:
            self.init_ftdi_driver()
            self._start_loop()

    def init_ftdi_driver(self):
        try:
            driver = Driver()
            devices = driver.list_devices()
            if not devices:
                self.logger.error("No FTDI devices found")
                sys.exit(1)
            for device in devices:
                manufacturer, description, serial = device
                if manufacturer == "FTDI":
                    if serial:
                        self.logger.info(f"Found FTDI port with serial {serial}")
                        self.ftdi_serial = serial
                        break
                    else:
                        self.logger.error("Serial number not available, eeprom may need to be reprogrammed (see 'eeprom' folder)")
                        sys.exit(1)

            if not self.ftdi_serial:
                self.logger.error("No FTDI devices with a valid serial found")
                sys.exit(1)

        except Exception as e:
            self.logger.error("Error initializing FTDI driver: %s", e)
            sys.exit(1)

    def _start_loop(self):
        self._running = True
        self._thread = threading.Thread(target=self._transmit_loop, daemon=True)
        self._thread.start()
        self.logger.info("Started DMX transmission loop.")

    def _transmit_loop(self):
        try:
            with Device(self.ftdi_serial) as ftdi_port:
                while self._running:
                    self.send_dmx_packet(ftdi_port, self.dmx_data)
                    time.sleep(0.025)  # roughly 40Hz
        except Exception as e:
            self.logger.error("DMX transmit loop crashed: %s", e)

    def send_message(self, address: int, data: bytes):
        if self.stub_mode:
            return
        assert self.ftdi_serial, "FTDI driver is not initialized"
        # Just update the buffer in memory! The transmit loop will pick it up instantly.
        self.dmx_data[address:address + len(data)] = data

    @staticmethod
    def send_dmx_packet(ftdi_port: Device, data: bytes):
        # reset dmx channel
        ftdi_port.ftdi_fn.ftdi_set_bitmode(1, 0x01)  # break
        ftdi_port.write(b'\x00')
        time.sleep(0.001)
        ftdi_port.write(b'\x01')
        ftdi_port.ftdi_fn.ftdi_set_bitmode(0, 0x00)  # release break
        ftdi_port.flush()
        ftdi_port.ftdi_fn.ftdi_set_line_property(8, 2, 0)
        ftdi_port.baudrate = 250000
        ftdi_port.write(bytes(data))
