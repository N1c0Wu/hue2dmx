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
