"""Explicit Fit closes whitespace; normal Save preserves hand-placed geometry."""
from copy import deepcopy
import itertools
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/poedash/assets/scripts'))
import dashboard_model as model


class FillCards(unittest.TestCase):
    def pixels(self,layout,width,height):
        return {k:[r[0]*width,r[1]*height,r[2]*width,r[3]*height] for k,r in layout.items()}

    def normalize(self,layout,width,height):
        return {k:[r[0]/width,r[1]/height,r[2]/width,r[3]/height] for k,r in layout.items()}

    def assert_filled(self,layout,width,height,gap,minimums=None):
        self.assertIsNotNone(layout)
        for key,rect in layout.items():
            self.assertTrue(model.valid_move(key,rect,layout),(key,rect,layout))
            if minimums:
                self.assertGreaterEqual(rect[2]*width,minimums[key][0]-1e-6)
                self.assertGreaterEqual(rect[3]*height,minimums[key][1]-1e-6)
        for a,b in itertools.combinations(layout.values(),2):self.assertTrue(model.spaced(a,b,width,height,gap))
        # Every edge meets the canvas or another card at the requested spacing.
        for key,(x,y,w,h) in self.pixels(layout,width,height).items():
            others=self.pixels({k:r for k,r in layout.items() if k!=key},width,height)
            right=width
            bottom=height
            for ox,oy,ow,oh in others.values():
                if min(y+h,oy+oh)>max(y,oy)+1e-6 and ox>=x+w-1e-6:right=min(right,ox-gap)
                if min(x+w,ox+ow)>max(x,ox)+1e-6 and oy>=y+h-1e-6:bottom=min(bottom,oy-gap)
            self.assertAlmostEqual(x+w,right,places=5)
            self.assertAlmostEqual(y+h,bottom,places=5)

    def test_one_card_fills_both_dimensions(self):
        self.assertEqual(model.fill_layout({'a':[.1,.2,.4,.3]},1000,800,6),{'a':[0,0,1,1]})

    def test_space_below_a_column_only_expands_its_last_card(self):
        original={'a':[0,0,500,150],'b':[0,156,500,200],'c':[0,362,500,100]}
        layout=self.normalize(original,500,700)
        result=model.fill_layout(layout,500,700,6)
        pixels=self.pixels(result,500,700)
        self.assertEqual(pixels['a'],original['a'])
        self.assertEqual(pixels['b'],original['b'])
        self.assertEqual(pixels['c'],[0,362,500,338])
        self.assert_filled(result,500,700,6)

    def test_extra_horizontal_gaps_are_shared_equally_between_unequal_cards(self):
        original={'a':[0,0,100,400],'b':[200,0,150,400],'c':[400,0,200,400]}
        layout=self.normalize(original,600,400)
        result=model.fill_layout(layout,600,400,10)
        pixels=self.pixels(result,600,400)
        gains=[pixels[k][2]-original[k][2] for k in layout]
        for value in gains:self.assertAlmostEqual(value,130/3)
        self.assertAlmostEqual(pixels['b'][0]-pixels['a'][2],10)
        self.assertAlmostEqual(pixels['c'][0]-pixels['b'][0]-pixels['b'][2],10)
        self.assert_filled(result,600,400,10)

    def test_extra_vertical_gaps_are_shared_equally_between_cards(self):
        original={'a':[0,0,600,100],'b':[0,150,600,100],'c':[0,300,600,100]}
        result=model.fill_layout(self.normalize(original,600,400),600,400,10)
        pixels=self.pixels(result,600,400)
        for key in original:self.assertAlmostEqual(pixels[key][3]-original[key][3],80/3)
        self.assert_filled(result,600,400,10)

    def test_trailing_space_in_a_row_expands_to_the_right(self):
        original={'a':[0,0,200,400],'b':[206,0,200,400]}
        result=model.fill_layout(self.normalize(original,600,400),600,400,6)
        pixels=self.pixels(result,600,400)
        self.assertEqual(pixels['a'],original['a'])
        self.assertEqual(pixels['b'],[206,0,394,400])
        self.assert_filled(result,600,400,6)

    def test_nested_columns_and_bottom_row_keep_order_and_fill_the_screen(self):
        original={'a':[0,0,300,150],'b':[0,156,300,300],
                  'c':[306,0,694,250],'d':[306,256,694,200],
                  'e':[0,462,300,100],'f':[306,462,300,100],'g':[612,462,388,100]}
        result=model.fill_layout(self.normalize(original,1000,800),1000,800,6)
        pixels=self.pixels(result,1000,800)
        for key in ('a','b','c','d'):self.assertEqual(pixels[key],original[key])
        for key in ('e','f','g'):self.assertAlmostEqual(pixels[key][1]+pixels[key][3],800)
        self.assert_filled(result,1000,800,6)

    def test_larger_spacing_reduces_cards_without_overlap_or_overflow(self):
        layout={'a':[0,0,.499,.499],'b':[.501,0,.499,.499],
                'c':[0,.501,.499,.499],'d':[.501,.501,.499,.499]}
        result=model.fill_layout(layout,1000,800,24)
        self.assert_filled(result,1000,800,24)

    def test_staggered_unsliceable_cards_are_packed_without_leaving_holes(self):
        layout={'a':[0,0,.6,.2],'b':[.8,0,.2,.6],
                'c':[.4,.8,.6,.2],'d':[0,.4,.2,.6]}
        result=model.fill_layout(layout,1000,800,10)
        self.assert_filled(result,1000,800,10)
        self.assertEqual(model.fill_layout(result,1000,800,10),result)

    def test_impossible_minimums_leave_the_input_untouched(self):
        layout={'a':[0,0,.4,.4],'b':[.6,0,.4,.4],'c':[0,.6,.4,.4],'d':[.6,.6,.4,.4]}
        before=deepcopy(layout)
        self.assertIsNone(model.fill_layout(layout,400,400,10,{k:(300,300) for k in layout}))
        self.assertEqual(layout,before)

    def test_fit_is_idempotent_deterministic_and_does_not_mutate_input(self):
        layout={'a':[.1,.1,.25,.25],'b':[.6,.1,.3,.25],'c':[.1,.6,.8,.3]}
        before=deepcopy(layout)
        result=model.fill_layout(layout,1000,800,6)
        self.assertEqual(layout,before)
        self.assertEqual(model.fill_layout(dict(reversed(list(layout.items()))),1000,800,6),result)
        self.assertEqual(model.fill_layout(result,1000,800,6),result)
        self.assert_filled(result,1000,800,6)

    def test_random_disjoint_card_sizes_remain_bounded_and_fully_expanded(self):
        randomizer=random.Random(42)
        for case in range(30):
            layout={}
            for index in range(12):
                for _ in range(100):
                    rect=[randomizer.uniform(0,.8),randomizer.uniform(0,.8),
                          randomizer.uniform(.06,.15),randomizer.uniform(.06,.15)]
                    if model.valid_move(str(index),rect,layout):layout[str(index)]=rect;break
            minimums={key:(40,50) for key in layout}
            with self.subTest(case=case):
                result=model.fill_layout(layout,1200,900,8,minimums)
                self.assert_filled(result,1200,900,8,minimums)
                self.assertEqual(model.fill_layout(result,1200,900,8,minimums),result)

    def test_empty_layout(self):
        self.assertEqual(model.fill_layout({},800,600,10),{})
