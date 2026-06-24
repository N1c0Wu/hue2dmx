import logging
from HueBridge import HueBridge

# Replace these with your actual IP and the API Key you just generated
BRIDGE_IP = "192.168.1.238"
API_KEY = "J-dCGeMIGURrKxpdGn4ueWoDzeSG2X9jPbFozp2v"

# Initialize the bridge
logger = logging.getLogger()
bridge = HueBridge(BRIDGE_IP, API_KEY, 240, logger)

# Fetch and print all lights
print("\n--- Your Hue Lights ---")
for hue_id, name in bridge.list_light_ids_and_names().items():
    print(f"Name: {name}")
    print(f"UUID: {hue_id}\n")
