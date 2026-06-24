# hue-dmx-controller (Advanced Palette Fork)

*This is a fork of the original [hue-dmx-controller](https://github.com/tomkalmijn/hue-dmx) by Tom Kalmijn.*

## What this script does
With this script you can seamlessly integrate DMX fixtures with your Philips Hue bridge and Hue mobile app. Unlike standard bridges, this fork features an advanced **Palette Manager** with color theory algorithms. It allows you to map entire arrays of DMX fixtures to just one or two Hue lights currently lighting your room, automatically generating beautiful gradients, complementary palettes, or triadic color schemes across your DMX universe.

There is no need for "dummy" or offline Hue bulbs. Just map the DMX fixtures directly to the active Hue lights already in your room, and the script will construct mathematical color palettes based on what the Hue lights are doing.

## New Features
- **Palette Manager**: Control multiple DMX fixtures from a single Hue light.
- **Color Theory Algorithms**: Automatically generate beautiful color schemes derived from your Hue lights:
  - `blend`: Smooth gradient between two Hue lights.
  - `to_complement`: A gradient from your Hue light to its mathematical complement.
  - `complementary`: A gradient between the complements of two Hue lights.
  - `triadic`: Generates a classic 3-color harmony based on your Hue light.
  - `tetradic`: Generates a vibrant 4-color harmony.
  - `split_complementary`: Generates a refined 3-color schema.
  - `analogous`: Maps colors to similar hues.
- **Distance Mapping**: Position fixtures physically along the generated gradient via a `distance` value.
- **Interpolation**: Choose between `smooth` (continuous gradient) and `discrete` (tuples/snapping strictly to exact theoretical colors).

## DMX Controller
In order to integrate DMX in your Hue system you need a DMX controller. This script is designed for FTDI-based bit-banging USB DMX controllers, such as the **ENTTEC Open DMX USB**. 

*Note: The more expensive **ENTTEC DMX USB PRO** is **not** supported, as it uses a different protocol rather than raw FTDI bit-banging.*

## Script Configuration

This fork uses a clean YAML configuration file (`fixtures.yml`) instead of environment variables to map your DMX universe to the Hue system.

### Example `fixtures.yml`

```yaml
hue:
  bridge_ip: 192.168.0.140
  api_key: YOUR_API_KEY
  timeout_sec: 240

dmx:
  stub: true # Set to false when your DMX USB controller is connected

palettes:
  - id: triadic_main
    type: two_lamps
    hue_light_ids:
      - "UUID-Base-Lamp"
      - "" # lamp_b is ignored for single-lamp algorithmic modes like triadic
    mode: triadic 
    max_distance: 6
    interpolation: discrete # fixtures snap strictly to the 3 triadic hues

fixtures:
  - name: WashLeft
    type: rgb
    palette: triadic_main
    distance: 0 # Picks the base hue
    channels: { r: 1, g: 2, b: 3 }
    steady: { "4": 255 } # Optionally map absolute channels to steady brightness

  - name: WashRight
    type: rgb
    palette: triadic_main
    distance: 2 # Picks the +120° hue
    channels: { r: 5, g: 6, b: 7 }

  - name: DimmerChannel
    type: steady # A fixture that just holds steady DMX values (ignores Hue entirely)
    channels: { "10": 255, "11": 0 }
```

You must pass the path to this file via the `FIXTURES_YAML` environment variable when starting the script.

## System Requirements
- Python 3.6 or higher
- Python FTDI driver (`pylibftdi`)
- `PyYAML`

## Usage

```bash
export FIXTURES_YAML=./fixtures.yml
python3 hue-dmx.py
```

## Running as a Background Service (Linux/Raspberry Pi)

To run the script automatically in the background whenever your system boots, you can set up a `systemd` service.

1. **Create a service file**:
   ```bash
   sudo nano /etc/systemd/system/hue2dmx.service
   ```

2. **Paste the following configuration**: *(Adjust the `/home/pi/hue2dmx` paths if your project is located elsewhere)*
   ```ini
   [Unit]
   Description=Hue to DMX Controller
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/hue2dmx
   # Set the environment variables
   Environment="FIXTURES_YAML=/home/pi/hue2dmx/fixtures.yml"
   Environment="RUNNING_AS_SERVICE=true"
   # Use the Python executable from inside your virtual environment
   ExecStart=/home/pi/hue2dmx/venv/bin/python3 hue-dmx.py

   Restart=always
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable hue2dmx.service
   sudo systemctl start hue2dmx.service
   ```

4. **View live logs**:
   ```bash
   sudo journalctl -u hue2dmx.service -f
   ```
