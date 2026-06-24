import os, sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from palette import build_two_lamp_palette

def test_blend_len_and_bounds():
    lst, hex_map = build_two_lamp_palette((255,0,0),(0,0,255),mode="blend",max_distance=5)
    assert len(lst) == 5 and len(hex_map) == 5
    assert hex_map[0].startswith("#") and len(hex_map[0]) == 7

def test_complementary_differs():
    lst1,_ = build_two_lamp_palette((10,20,30),(40,50,60),mode="blend",max_distance=3)
    lst2,_ = build_two_lamp_palette((10,20,30),(40,50,60),mode="complementary",max_distance=3)
    assert lst1 != lst2

def test_analogous_with_shift():
    lst,_ = build_two_lamp_palette((200,200,0),(0,200,200),mode="analogous",max_distance=7,analogous_shift_deg=30)
    assert len(lst) == 7

def test_triadic_discrete():
    # Triadic has 3 colors. Max distance 6 means we should snap to exactly 3 colors
    lst,_ = build_two_lamp_palette((255,0,0),(0,0,0),mode="triadic",max_distance=6,interpolation="discrete")
    # Using a set should yield exactly 3 unique RGB values
    unique_colors = set(lst)
    assert len(unique_colors) == 3

def test_triadic_smooth():
    # Smooth interpolation should yield multiple intermediate colors
    lst,_ = build_two_lamp_palette((255,0,0),(0,0,0),mode="triadic",max_distance=6,interpolation="smooth")
    unique_colors = set(lst)
    assert len(unique_colors) > 3

def test_tetradic():
    lst,_ = build_two_lamp_palette((0,255,0),(0,0,0),mode="tetradic",max_distance=4,interpolation="discrete")
    assert len(set(lst)) == 4

def test_split_complementary():
    lst,_ = build_two_lamp_palette((0,0,255),(0,0,0),mode="split_complementary",max_distance=3,interpolation="discrete")
    assert len(set(lst)) == 3

def test_to_complement():
    lst,_ = build_two_lamp_palette((255,0,0),(0,0,0),mode="to_complement",max_distance=2,interpolation="discrete")
    assert len(set(lst)) == 2

def test_palette_manager_offset():
    from PaletteManager import PaletteManager, PaletteConfig
    from HueModel import HueLight, On, Color, Point, Gamut, GamutPoint, Dimming, Metadata, Owner
    
    pm = PaletteManager()
    cfg = PaletteConfig(
        pid="test_p",
        lamp_a="lamp1",
        lamp_b="lamp2",
        mode="blend",
        max_distance=5,
        analogous_shift_deg=0.0
    )
    pm.register_palette(cfg)
    
    l1 = HueLight(
        type="light",
        id="lamp1",
        owner=Owner(rid="o1", rtype="device"),
        on=On(on=True),
        color=Color(
            xy=Point(x=0.675, y=0.322),
            gamut=Gamut(
                red=GamutPoint(x=0.675, y=0.322),
                green=GamutPoint(x=0.409, y=0.518),
                blue=GamutPoint(x=0.167, y=0.04)
            )
        ),
        dimming=Dimming(brightness=100.0),
        metadata=Metadata(function="mixed")
    )
    l2 = HueLight(
        type="light",
        id="lamp2",
        owner=Owner(rid="o2", rtype="device"),
        on=On(on=True),
        color=Color(
            xy=Point(x=0.167, y=0.04),
            gamut=Gamut(
                red=GamutPoint(x=0.675, y=0.322),
                green=GamutPoint(x=0.409, y=0.518),
                blue=GamutPoint(x=0.167, y=0.04)
            )
        ),
        dimming=Dimming(brightness=100.0),
        metadata=Metadata(function="mixed")
    )
    
    pm.update_from_hue_event(l1)
    pm.update_from_hue_event(l2)
    
    c0 = pm.get_color_for("test_p", 0, offset=0)
    c1 = pm.get_color_for("test_p", 0, offset=1)
    c5 = pm.get_color_for("test_p", 0, offset=5)
    c8 = pm.get_color_for("test_p", 0, offset=8)
    
    assert c0 != c1
    assert c0 == c8
    c3 = pm.get_color_for("test_p", 0, offset=3)
    assert c5 == c3

