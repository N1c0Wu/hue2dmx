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
