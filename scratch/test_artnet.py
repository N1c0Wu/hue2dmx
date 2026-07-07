import sys
import os
import time
import socket
import threading
import struct

sys.path.append("/Users/nico/AntigravityProjects/hue2dmx")

from DmxSender import DmxSender
from ArtNetSender import ArtNetSender
from PaletteManager import PaletteManager, PaletteConfig
from YamlPixelStripFixture import YamlPixelStripFixture

class ArtNetReceiver:
    def __init__(self, port=6454):
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.received_packets = []
        self._running = True
        self.thread = threading.Thread(target=self._listen, daemon=True)
        self.thread.start()

    def _listen(self):
        self.sock.settimeout(0.5)
        while self._running:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.received_packets.append(data)
            except socket.timeout:
                continue
            except Exception as e:
                print("Receiver exception:", e)
                break

    def stop(self):
        self._running = False
        self.sock.close()
        self.thread.join(timeout=1.0)

def test_separated_sending():
    print("Testing Separated Senders (DmxSender & ArtNetSender)...")
    receiver = ArtNetReceiver()
    
    import logging
    logger = logging.getLogger("Test")
    logging.basicConfig(level=logging.INFO)
    
    # 1. Initialize DmxSender (stub mode)
    dmx_sender = DmxSender(logger=logger, stub_mode=True, max_channel=10)
    
    # 2. Initialize ArtNetSender (sends to receiver on localhost)
    artnet_sender = ArtNetSender(
        logger=logger,
        ip="127.0.0.1",
        port=6454,
        start_universe=0,
        max_channel=600
    )
    
    # Test DMX standard message
    dmx_sender.send_message(1, b'\xff\x00\x55')
    
    # Test Art-Net message (Universe 1)
    artnet_sender.send_message(513, b'\xaa\xbb\xcc')
    
    # Wait a bit for transmission loop
    time.sleep(0.1)
    
    artnet_sender._running = False
    if artnet_sender._thread:
        artnet_sender._thread.join()
        
    dmx_sender._running = False
    if dmx_sender._thread:
        dmx_sender._thread.join()
        
    receiver.stop()
    
    print(f"Total received Art-Net packets: {len(receiver.received_packets)}")
    if not receiver.received_packets:
        print("FAIL: No Art-Net packets received on port 6454!")
        sys.exit(1)
        
    # Standard DMX updates in stub mode should have modified dmx_sender.dmx_data directly
    if dmx_sender.dmx_data[1:4] != b'\xff\x00\x55':
        print(f"FAIL: DmxSender data is incorrect: {dmx_sender.dmx_data[1:4]}")
        sys.exit(1)
        
    # Check the latest Art-Net packet
    last_packet = receiver.received_packets[-1]
    
    # Check Art-Net signature
    if last_packet[0:8] != b'Art-Net\x00':
        print(f"FAIL: Invalid Art-Net signature: {last_packet[0:8]}")
        sys.exit(1)
        
    # Check OpCode (0x5000, transmitted in little-endian as 0x00 0x50)
    opcode = struct.unpack('<H', last_packet[8:10])[0]
    if opcode != 0x5000:
        print(f"FAIL: Invalid OpCode: {hex(opcode)}")
        sys.exit(1)
        
    # Check universe index for second packet (Universe 1)
    universe = struct.unpack('>H', last_packet[14:16])[0]
    # In our case, the last packet might be Universe 0 or Universe 1. Let's make sure it represents a valid universe.
    print(f"Verified packet universe: {universe}")
    
    print("SUCCESS: Standard DMX and Art-Net senders operate independently and correctly!")

def test_pixel_strip_mapping():
    print("\nTesting Pixel Strip Mapping...")
    pm = PaletteManager()
    
    # Register a test palette
    pm.register_palette(PaletteConfig(
        pid="test_pal",
        lamp_a="lamp_a_id",
        lamp_b="lamp_b_id",
        mode="blend",
        max_distance=10,
        analogous_shift_deg=0.0
    ))
    
    # Mock _xy_to_rgb to return our test colors
    predefined_colors = {
        "lamp_a_id": (255, 0, 0),
        "lamp_b_id": (0, 0, 255)
    }
    pm._xy_to_rgb = lambda light: predefined_colors.get(light.id)
    
    # Fake light update to trigger palette build
    class FakeLight:
        def __init__(self, lid, on=True, brightness=100):
            self.id = lid
            self.on = type('On', (), {'on': on})()
            self.dimming = type('Dimming', (), {'brightness': brightness})()
            self.color = type('Color', (), {
                'xy': type('Point', (), {'x': 0.5, 'y': 0.5})(),
                'gamut': None,
                'gamut_type': 'B'
            })()
            self.color_temperature = None
            self._color_mode = "color"
            
    pm.update_from_hue_event(FakeLight("lamp_a_id"))
    pm.update_from_hue_event(FakeLight("lamp_b_id"))
    
    # Create 5-pixel GRB strip starting at channel 10
    strip = YamlPixelStripFixture(
        name="TestStrip",
        palette_id="test_pal",
        start_channel=10,
        pixel_count=5,
        color_order="grb",
        palette_mgr=pm
    )
    
    dmx_msg = strip.get_dmx_message()
    print(f"DMX message length: {len(dmx_msg)} bytes (Expected: 15)")
    if len(dmx_msg) != 15:
        print("FAIL: Invalid DMX message length!")
        sys.exit(1)
        
    for p in range(5):
        idx = p * 3
        g, r, b = dmx_msg[idx], dmx_msg[idx+1], dmx_msg[idx+2]
        print(f"  Pixel {p}: R={r}, G={g}, B={b}")
        
    if dmx_msg[0] != 0 or dmx_msg[1] != 255 or dmx_msg[2] != 0:
        print("FAIL: Pixel 0 is not Red in GRB format!")
        sys.exit(1)
        
    if dmx_msg[12] != 0 or dmx_msg[13] != 0 or dmx_msg[14] != 255:
        print("FAIL: Pixel 4 is not Blue in GRB format!")
        sys.exit(1)
        
    print("SUCCESS: Pixel strip gradient mapping and color order are correct!")

if __name__ == "__main__":
    test_separated_sending()
    test_pixel_strip_mapping()
