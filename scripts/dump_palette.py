from palette import build_two_lamp_palette

# Beispiel: zwei RGB-Farben (Rot, Blau), Modus blend, 10 Schritte
rgb_a = (255, 0, 0)
rgb_b = (0, 0, 255)
lst, hex_map = build_two_lamp_palette(rgb_a, rgb_b, mode="blend", max_distance=10)

for i in range(10):
    print(f"{i}: {hex_map[i]}  {lst[i]}")
