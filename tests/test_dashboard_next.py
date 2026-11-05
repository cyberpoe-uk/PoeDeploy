"""Editable desktop model, persistence, history and collector contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'apps/poedash/assets/scripts'
sys.path.insert(0,str(SCRIPTS))
import dashboard_model as model
import dashboard_collect as collect


class Configuration(unittest.TestCase):
    def test_defaults_roundtrip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=model.Settings(tmp)
            self.assertEqual(set(store.data['profiles']),{'Daily','Monitoring','Minimal'})
            store.save()
            self.assertEqual(model.Settings(tmp).data,store.data)
            self.assertEqual(store.path.stat().st_mode & 0o777,0o600)
            self.assertEqual(store.profile['refresh']['cpu'],2)

    def test_invalid_settings_are_preserved_before_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'dashboard.json'; path.write_text('{"version":99}')
            store=model.Settings(tmp)
            self.assertTrue(store.error)
            backups=list(Path(tmp).glob('dashboard.invalid-*.json'))
            self.assertEqual(len(backups),1)
            self.assertEqual(json.loads(backups[0].read_text()),{'version':99})
            store.save(); model.validate(json.loads(path.read_text()))

    def test_recent_app_defaults_upgrade_existing_profiles_without_losing_data(self):
        data=model.defaults(); data['notes']='keep my note'
        for profile in data['profiles'].values():
            profile['appearance'].pop('recent_text_size')
            profile['appearance'].pop('recent_icon_size')
        model.validate(data)
        self.assertEqual(data['notes'],'keep my note')
        for profile in data['profiles'].values():
            self.assertEqual(profile['appearance']['recent_text_size'],14)
            self.assertEqual(profile['appearance']['recent_icon_size'],40)

    def test_validation_rejects_bad_intervals_coordinates_and_layouts(self):
        for mutate in [
            lambda d:d['profiles']['Daily']['refresh'].update(cpu=0),
            lambda d:d['profiles']['Daily']['refresh'].update(cpu=True),
            lambda d:d['profiles']['Daily']['refresh'].update(cpu=100000),
            lambda d:d['profiles']['Daily']['appearance'].update(opacity=float('nan')),
            lambda d:d['profiles']['Daily']['appearance'].update(scale=0),
            lambda d:d['profiles']['Daily']['appearance'].update(scale=3),
            lambda d:d['profiles']['Daily']['appearance'].update(recent_text_size=8),
            lambda d:d['profiles']['Daily']['appearance'].update(recent_icon_size=81),
            lambda d:d['profiles']['Daily']['appearance'].update(recent_icon_size=True),
            lambda d:d['profiles']['Daily']['layouts'].update(display={'arch':[.9,0,.5,.2]}),
            lambda d:d['integrations']['remote'].update(url='file:///etc/passwd'),
            lambda d:d['integrations']['weather'].update(latitude='200'),
            lambda d:d['integrations']['feeds'].update(urls='file:///tmp/feed.xml'),
            lambda d:d.update(expected_shares=['relative/path']),
        ]:
            data=model.defaults(); mutate(data)
            with self.assertRaises(ValueError): model.validate(data)

    def test_undo_redo_and_cancel_leave_original_untouched(self):
        original=model.defaults(); transaction=model.Transaction(original)
        transaction.checkpoint(); transaction.data['notes']='first'
        transaction.checkpoint(); transaction.data['notes']='second'
        self.assertTrue(transaction.undo()); self.assertEqual(transaction.data['notes'],'first')
        self.assertTrue(transaction.redo()); self.assertEqual(transaction.data['notes'],'second')
        transaction.undo(); transaction.checkpoint(); transaction.data['notes']='replacement'
        self.assertFalse(transaction.redo())
        self.assertEqual(original['notes'],'')
        self.assertEqual(transaction.original,original)

    def test_monitor_layouts_and_profiles_are_independent(self):
        data=model.defaults()
        profile=data['profiles']['Daily']
        profile['layouts']['laptop']={'arch':[0,0,.3,.2]}
        profile['layouts']['monitor']={'arch':[0,0,.2,.3]}
        profile['refresh']['cpu']=10
        self.assertNotEqual(profile['layouts']['laptop'],profile['layouts']['monitor'])
        self.assertEqual(data['profiles']['Monitoring']['refresh']['cpu'],2)
        model.validate(data)


class Layout(unittest.TestCase):
    def test_every_card_fits_without_collisions_across_sizes(self):
        for size in [(320,480),(700,800),(1300,800),(2000,1200),(3500,1900)]:
            for cards in [model.BASE_CARDS,list(model.CARDS),model.defaults()['profiles']['Minimal']['visible'],[]]:
                layout=model.default_layout(cards,*size)
                self.assertEqual(set(layout),set(cards))
                for key,rect in layout.items():
                    self.assertTrue(model.valid_move(key,rect,layout),(size,key,rect))

    def test_move_is_bounded_and_collision_is_rejected(self):
        layout={'a':[0,0,.3,.3],'b':[.4,0,.3,.3]}
        moved,_=model.transform(layout['a'],450,0,'',1000,800)
        self.assertFalse(model.valid_move('a',moved,layout))
        bounded,_=model.transform(layout['a'],-2000,-2000,'',1000,800)
        self.assertEqual(bounded[:2],[0,0])
        bounded,_=model.transform(layout['a'],5000,5000,'',1000,800)
        self.assertTrue(model.valid_rect(bounded))
        self.assertAlmostEqual(bounded[0]+bounded[2],1)

    def test_all_eight_resize_directions_preserve_opposite_edges(self):
        rect=[.2,.2,.3,.3]
        for edge in ('n','s','e','w','nw','ne','sw','se'):
            result,_=model.transform(rect,20,20,edge,1000,1000)
            self.assertTrue(model.valid_rect(result))
            if 'w' in edge: self.assertAlmostEqual(result[0]+result[2],.5)
            if 'n' in edge: self.assertAlmostEqual(result[1]+result[3],.5)
            if 'e' in edge: self.assertEqual(result[0],.2)
            if 's' in edge: self.assertEqual(result[1],.2)
        minimum,_=model.transform(rect,10000,10000,'nw',1000,1000)
        self.assertGreaterEqual(minimum[2],.18-1e-9)
        self.assertGreaterEqual(minimum[3],.1-1e-9)

    def test_dropping_onto_occupied_slot_proposes_valid_swap(self):
        layout={'a':[0,0,.3,.3],'b':[.4,0,.4,.5]}
        proposed=[.45,.05,.3,.3]
        self.assertEqual(model.swap_target('a',proposed,layout),'b')
        self.assertIsNone(model.swap_target('a',[.1,.6,.3,.3],layout))
        self.assertEqual(layout['a'],[0,0,.3,.3])

    def test_snap_generates_alignment_guides(self):
        rect=[.1,.1,.2,.2]
        result,guides=model.transform(rect,98,0,'',1000,1000,12,[[.2,.3,.2,.2]])
        self.assertAlmostEqual(result[0],.2)
        self.assertIn(('x',200),guides)


class LocalHistory(unittest.TestCase):
    def test_retention_and_downsampling_keep_recent_history_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            history=model.History(Path(tmp)/'history.db')
            history.add({'cpu':10},now=100)
            for stamp in range(4000,4500): history.add({'cpu':stamp%100},now=stamp)
            values=history.series('cpu',60,now=4500,limit=50)
            self.assertLessEqual(len(values),50)
            self.assertTrue(all(stamp>=900 for stamp,value in values))
            self.assertEqual(history.db.execute('select count(*) from samples where time=100').fetchone()[0],0)
            history.add({'cpu':float('nan'),'gpu':None},now=4500)
            self.assertEqual(history.series('gpu',60,4500),[])
            history.close()


class Collectors(unittest.TestCase):
    def test_no_requests_are_made_for_unconfigured_integrations(self):
        collector=collect.Collectors(Path('/tmp/unused'))
        for source in ('weather','nas','remote','feeds'):
            with patch.object(collect,'fetch',side_effect=AssertionError('Unexpected request')):
                self.assertFalse(collector.collect(source,model.defaults())['configured'])

    def test_rss_and_atom_are_read_and_unsafe_links_removed(self):
        rss=b'<rss><channel><item><title>News</title><link>https://example.com/news</link></item></channel></rss>'
        self.assertEqual(collect.feed_items(rss),[{'title':'News','url':'https://example.com/news'}])
        atom=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Post</title><link href="https://example.com/post"/></entry></feed>'
        self.assertEqual(collect.feed_items(atom)[0]['url'],'https://example.com/post')
        self.assertEqual(collect.feed_items(rss.replace(b'https://example.com/news',b'javascript:evil()'))[0]['url'],'')
        with self.assertRaises(ValueError): collect.feed_items(b'<!DOCTYPE feed [<!ENTITY x "bad">]><feed/>')

    def test_nested_shares_and_expected_disconnections(self):
        payload={'filesystems':[{'target':'/mnt/a','source':'server:/a','fstype':'nfs4','children':[{'target':'/mnt/b','source':'//server/b','fstype':'cifs'}]}]}
        mounts=collect.mounted_shares(payload)
        self.assertEqual(len(mounts),2)
        issues=collect.health_issues({'shares':mounts},['/mnt/a','/mnt/missing'])
        self.assertEqual(issues,[{'card':'shares','text':'Share disconnected: /mnt/missing'}])
        self.assertEqual(collect.health_issues({},['/mnt/missing']),[])

    def test_health_summary_reports_actionable_conditions(self):
        values={'health':{'disks':[{'path':'/','percent':95}],'failed':['broken.service']},
                'network':{'state':'Offline'},'power':{'on_battery':True,'battery':'10%'}}
        issues=collect.health_issues(values)
        self.assertEqual(len(issues),4)
        self.assertEqual({i['card'] for i in issues},{'system','connectivity','power'})

    def test_vpn_monitoring_is_opt_in(self):
        values={'vpn':{'tailscale':False,'proton':False}}
        self.assertEqual(collect.health_issues(values),[])
        self.assertEqual(len(collect.health_issues(values,expected_vpns=['tailscale'])),1)

    def test_json_endpoint_and_weather_contracts(self):
        collector=collect.Collectors('/tmp/unused'); settings=model.defaults()
        settings['integrations']['remote']={'url':'https://example.com/metrics','token':'private'}
        with patch.object(collect,'fetch',return_value={'cpu':18}) as fetch:
            self.assertEqual(collector.collect('remote',settings)['data']['cpu'],18)
            fetch.assert_called_once_with('https://example.com/metrics','private')
        with patch.object(collect,'fetch',return_value=[]):
            with self.assertRaises(ValueError): collector.collect('remote',settings)
        settings['integrations']['weather']={'latitude':'51.5','longitude':'-0.1'}
        with patch.object(collect,'fetch',return_value={'current':{'temperature_2m':14}}) as fetch:
            self.assertTrue(collector.collect('weather',settings)['configured'])
            self.assertIn('latitude=51.5',fetch.call_args.args[0])

    def test_subprocess_timeout_kills_and_reaps_child(self):
        collector=collect.Collectors('/tmp/unused')
        with self.assertRaisesRegex(RuntimeError,'timed out'):
            collector.run([sys.executable,'-c','import time; time.sleep(10)'],timeout=.05)
        self.assertFalse(collector.processes)


class Scheduling(unittest.TestCase):
    def test_slow_general_sources_do_not_block_player_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings=model.defaults()
            engine=collect.Engine(tmp,settings,lambda payload:None)
            engine.visibility_override=True
            release=threading.Event(); media=threading.Event()
            def reading(source,settings):
                if source=='media': media.set(); return {'status':'Paused'}
                release.wait(3); return 1
            engine.collectors.collect=reading
            with patch.object(collect,'battery_reading',return_value={'on_battery':False}):
                engine.start()
                try: self.assertTrue(media.wait(1),'Player was queued behind general collectors')
                finally: release.set(); engine.close()

    def test_configured_rates_and_pause_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings=model.defaults()
            settings['profiles']['Daily']['visible']=['performance']
            settings['profiles']['Daily']['refresh'].update(cpu=60,cpu_temperature=60,ram=60,gpu=60,health=60,power=60)
            engine=collect.Engine(tmp,settings,lambda payload:None)
            engine.visibility_override=True
            calls=[]
            def reading(source,settings): calls.append(source); return 1
            engine.collectors.collect=reading
            with patch.object(collect,'battery_reading',return_value={'on_battery':True}):
                engine.start(); time.sleep(.5)
                self.assertEqual(calls.count('cpu'),1)
                engine.visibility_override=False
                time.sleep(2.1)
                self.assertTrue(engine.paused)
                before=len(calls); time.sleep(.25); self.assertEqual(before,len(calls))
                engine.visibility_override=True
                time.sleep(2.1)
                self.assertFalse(engine.paused)
                self.assertEqual(calls.count('cpu'),2)
                engine.close()
            self.assertFalse(engine.thread.is_alive())


class WeatherLocationSearch(unittest.TestCase):
    def test_results_distinguish_places_and_keep_coordinates(self):
        payload={'results':[{'name':'Cambridge','admin1':'England','country':'United Kingdom','latitude':52.2,'longitude':.12},
                            {'name':'Cambridge','admin1':'Massachusetts','country':'United States','latitude':42.37,'longitude':-71.1}]}
        with patch.object(collect,'fetch',return_value=payload) as fetch:
            values=collect.search_weather_locations('Cambridge')
        self.assertEqual(len(values),2)
        self.assertIn('United Kingdom',values[0]['location'])
        self.assertIn('Massachusetts',values[1]['location'])
        self.assertEqual(values[1]['longitude'],'-71.1')
        self.assertIn('name=Cambridge',fetch.call_args.args[0])

    def test_empty_and_malformed_results_do_not_select_a_place(self):
        with patch.object(collect,'fetch',return_value={}):self.assertEqual(collect.search_weather_locations('Unknown'),[])
        with patch.object(collect,'fetch',return_value={'results':[{'name':'Bad','latitude':float('nan'),'longitude':0},{'name':'Missing'}]}):
            self.assertEqual(collect.search_weather_locations('Unknown'),[])
        with patch.object(collect,'fetch') as fetch:
            with self.assertRaises(ValueError):collect.search_weather_locations('A')
            fetch.assert_not_called()

    def test_saved_place_name_is_optional_for_existing_coordinates(self):
        data=model.defaults();data['integrations']['weather']={'latitude':'52.2','longitude':'.12'}
        model.validate(data)
        data['integrations']['weather']['location']='Cambridge, England, United Kingdom'
        model.validate(data)


class AdaptiveLayout(unittest.TestCase):
    def assert_valid(self,plan):
        self.assertIsNotNone(plan)
        for key,rect in plan.items():self.assertTrue(model.valid_move(key,rect,plan),(key,rect,plan))

    def test_move_exchanges_unequal_slots_and_fits_both_cards(self):
        layout={'a':[0,0,.2,.3],'b':[.4,0,.5,.6]};before=deepcopy(layout)
        result=model.resolve_layout('a',[.45,.15,.2,.3],layout,'',1000,1000)
        self.assert_valid(result)
        self.assertEqual(result['a'],layout['b']);self.assertEqual(result['b'],layout['a'])
        self.assertEqual(layout,before)

    def test_resize_shrinks_horizontal_and_vertical_neighbours(self):
        layout={'a':[0,0,.3,.4],'b':[.31,0,.3,.4]}
        result=model.resolve_layout('a',[0,0,.4,.4],layout,'e',1000,1000)
        self.assert_valid(result);self.assertAlmostEqual(result['b'][0],.41);self.assertAlmostEqual(result['b'][2],.2)
        layout={'a':[0,0,.4,.3],'b':[0,.31,.4,.3]}
        result=model.resolve_layout('a',[0,0,.4,.45],layout,'s',1000,1000)
        self.assert_valid(result);self.assertAlmostEqual(result['b'][1],.46);self.assertAlmostEqual(result['b'][3],.15)

    def test_west_and_north_resize_keep_far_edges_fixed(self):
        layout={'a':[0,0,.3,.4],'b':[.31,0,.3,.4]}
        result=model.resolve_layout('b',[.2,0,.41,.4],layout,'w',1000,1000)
        self.assert_valid(result);self.assertAlmostEqual(result['a'][2],.19)
        layout={'a':[0,0,.4,.3],'b':[0,.31,.4,.3]}
        result=model.resolve_layout('b',[0,.2,.4,.41],layout,'n',1000,1000)
        self.assert_valid(result);self.assertAlmostEqual(result['a'][3],.19)

    def test_resize_stops_before_crushing_neighbour_and_preserves_unrelated_cards(self):
        layout={'a':[0,0,.3,.4],'b':[.31,0,.3,.4],'c':[.62,0,.38,.4]}
        result=model.resolve_layout('a',[0,0,.85,.4],layout,'e',1000,1000)
        self.assert_valid(result)
        self.assertGreaterEqual(result['b'][2],.18-1e-7)
        self.assertLessEqual(result['a'][2],.421)
        self.assertEqual(result['c'],layout['c'])

    def test_corner_resize_can_adjust_multiple_cards(self):
        layout={'a':[0,0,.3,.3],'b':[.31,0,.3,.3],'c':[0,.31,.3,.3],'d':[.31,.31,.3,.3]}
        result=model.resolve_layout('a',[0,0,.4,.4],layout,'se',1000,1000)
        self.assert_valid(result)
        self.assertNotEqual(result['b'],layout['b']);self.assertNotEqual(result['c'],layout['c'])

    def test_empty_space_and_invalid_bounds(self):
        layout={'a':[0,0,.3,.3]}
        self.assertEqual(model.resolve_layout('a',[.5,.5,.3,.3],layout,'',1000,1000)['a'],[.5,.5,.3,.3])
        self.assertIsNone(model.resolve_layout('a',[.9,.9,.3,.3],layout,'',1000,1000))


class StableLayoutsAndGaps(unittest.TestCase):
    def test_insert_into_free_space_keeps_existing_rectangles(self):
        layout={'arch':[0,0,.3,.4],'system':[.31,0,.3,.4]}
        result,height=model.insert_card('weather',layout,1000,800,10)
        self.assertEqual(height,800)
        for key in layout:self.assertEqual(result[key],layout[key])
        self.assertTrue(all(model.spaced(result['weather'],r,1000,height,10) for k,r in result.items() if k!='weather'))

    def test_full_canvas_shares_column_height_without_scrolling(self):
        layout={'arch':[0,0,1,1]}
        result,height=model.insert_card('weather',layout,600,400,14)
        self.assertEqual(height,400)
        self.assertGreaterEqual(result['arch'][3]*height,100)
        self.assertGreaterEqual(result['weather'][3]*height,100)
        self.assertAlmostEqual((result['weather'][1]-result['arch'][3])*height,14)

    def test_swapping_requires_release_and_central_target(self):
        layout={'a':[0,0,.3,.3],'b':[.4,0,.4,.5]};rect=[.45,.05,.3,.3]
        self.assertIsNone(model.resolve_layout('a',rect,layout,'',1000,1000,allow_swap=False))
        self.assertIsNotNone(model.resolve_layout('a',rect,layout,'',1000,1000,drop_point=(.6,.25)))
        self.assertIsNone(model.resolve_layout('a',rect,layout,'',1000,1000,drop_point=(.41,.25)))
        self.assertIsNone(model.resolve_layout('a',rect,layout,'',1000,1000,drop_point=(.6,.49)))

    def test_free_slot_wins_over_a_nearby_card(self):
        layout={'a':[0,0,.2,.2],'b':[.5,.1,.3,.3]}
        rect=[.29,.1,.2,.2]
        result=model.resolve_layout('a',rect,layout,'',1000,1000,10)
        self.assertEqual(result['a'],rect);self.assertEqual(result['b'],layout['b'])

    def test_snap_uses_configured_gap_and_no_distant_grid_rounding(self):
        rect=[.1,.1,.2,.2];other=[.4,.1,.2,.2]
        result,guides=model.transform(rect,87,0,'',1000,1000,12,[other],10)
        self.assertAlmostEqual((other[0]-result[0]-result[2])*1000,10)
        result,_=model.transform(rect,37,19,'',1000,1000,12,[[.6,.7,.2,.2]],10)
        self.assertAlmostEqual(result[0],.137);self.assertAlmostEqual(result[1],.119)

    def test_resize_preserves_gap_before_cards_physically_overlap(self):
        layout={'a':[0,0,.3,.4],'b':[.31,0,.3,.4]}
        result=model.resolve_layout('a',[0,0,.305,.4],layout,'e',1000,1000,10)
        self.assertAlmostEqual((result['b'][0]-result['a'][2])*1000,10)

    def test_gap_measurements_report_exact_spacing(self):
        layout={'a':[0,0,.3,.3],'b':[.31,0,.3,.3],'c':[0,.32,.3,.3]}
        gaps=model.measure_gaps('a',layout['a'],layout,1000,1000)
        self.assertEqual(sorted(round(g[-1]) for g in gaps),[10,20])


class FitCardsWithinScreen(unittest.TestCase):
    def test_full_column_shares_reduction_with_cards_above(self):
        layout={'arch':[0,0,1,.3],'system':[0,.3125,1,.6875]}
        result,height=model.insert_card('weather',layout,600,800,10)
        self.assertEqual(height,800)
        self.assertLess(result['arch'][3],layout['arch'][3])
        self.assertLess(result['system'][3],layout['system'][3])
        reduction1=(layout['arch'][3]-result['arch'][3])*height
        reduction2=(layout['system'][3]-result['system'][3])*height
        self.assertAlmostEqual(reduction1,reduction2)
        self.assertTrue(model.spaced(result['system'],result['weather'],600,800,10))

    def test_column_shares_height_reduction_equally_when_bottom_is_too_short(self):
        layout={k:[0,i*230/700,1,220/700] for i,k in enumerate(('arch','system','power'))}
        result,height=model.insert_card('weather',layout,600,700,10)
        self.assertEqual(height,700)
        heights=[result[k][3]*height for k in layout]
        self.assertTrue(all(abs(h-heights[0])<.01 for h in heights))
        for key,rect in result.items():self.assertTrue(model.valid_move(key,rect,result))
        self.assertAlmostEqual((result['weather'][1]+result['weather'][3])*height,700)

    def test_no_room_does_not_extend_canvas_or_change_layout(self):
        layout={'arch':[0,0,1,1]};original=deepcopy(layout)
        result,height=model.insert_card('weather',layout,600,200,10)
        self.assertIsNone(result);self.assertEqual(height,200);self.assertEqual(layout,original)

    def test_fit_to_screen_preserves_columns_and_usable_sizes(self):
        layout={'arch':[0,0,.49,.4],'system':[0,.41,.49,.59],'player':[.51,0,.49,1]}
        result,height=model.fit_layout_height(layout,1000,1000,600,10)
        self.assertIsNotNone(result);self.assertEqual(height,600)
        for key,rect in result.items():
            self.assertEqual(rect[0],layout[key][0]);self.assertEqual(rect[2],layout[key][2])
            self.assertGreaterEqual(rect[3]*height,100)
            self.assertTrue(model.valid_move(key,rect,result))
        self.assertTrue(model.spaced(result['arch'],result['system'],1000,height,10))

    def test_fit_refuses_to_crush_cards_below_minimum_height(self):
        layout={k:[0,i*110/330,1,100/330] for i,k in enumerate(('arch','system','power'))}
        result,height=model.fit_layout_height(layout,600,330,250,10)
        self.assertIsNone(result);self.assertEqual(height,250)


class FixedCanvasRegression(unittest.TestCase):
    def test_refitting_an_already_valid_layout_is_exactly_stable(self):
        layout={'arch':[0,0,.4,.3],'system':[0,.31,.4,.3]}
        result,height=model.fit_layout_height(layout,1000,1000,1000,10)
        self.assertEqual(result,layout)
        self.assertEqual(model.fit_layout_height(result,1000,height,height,10)[0],layout)

    def test_adding_card_preserves_other_columns(self):
        layout={'arch':[0,0,.49,.49],'system':[0,.51,.49,.49],
                'performance':[.51,0,.49,.49],'processes':[.51,.51,.49,.49]}
        result,height=model.insert_card('weather',layout,1000,600,10)
        self.assertEqual(height,600)
        changed=[key for key in layout if result[key]!=layout[key]]
        self.assertEqual(len(changed),2)
        self.assertEqual(len({layout[key][0] for key in changed}),1)
        for key,rect in result.items():self.assertTrue(model.valid_move(key,rect,result))
