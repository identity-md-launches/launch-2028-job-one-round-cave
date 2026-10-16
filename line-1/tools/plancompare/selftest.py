"""Offline behavioral tests; writes disposable CLI fixtures only in test/scratch."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest
import plancompare as p


class CompareTests(unittest.TestCase):
    def test_demo(self):
        r = p.compare(*p.demo(), workers=2, budget=8)
        self.assertTrue(r['comparable'])
        self.assertEqual(r['finish_delta'], '-2')
        self.assertEqual(r['counts'], dict(earlier=2, later=0, same_time=1, worker_moves=1))
        self.assertEqual(r['after_deadline_margin'], '3')

    def test_reverse(self):
        t, a, b = p.demo()
        r = p.compare(t, b, a, 2)
        self.assertEqual(r['finish_delta'], '2')
        self.assertEqual(r['counts']['later'], 2)

    def test_invalid_has_no_deltas(self):
        t, a, b = p.demo()
        for target in ('before', 'after'):
            aa, bb = copy.deepcopy(a), copy.deepcopy(b)
            (aa if target == 'before' else bb)['schedule'][0]['finish'] = 3
            r = p.compare(t, aa, bb, 2)
            self.assertFalse(r['comparable'])
            self.assertNotIn('tasks', r)
            self.assertIn('duration_mismatch:build', r['checks'][target]['violations'])

    def test_deadline(self):
        r = p.compare(*p.demo(), workers=2, budget=6)
        self.assertFalse(r['comparable'])
        self.assertEqual(r['checks']['before']['violations'], ['deadline_exceeded'])
        self.assertTrue(r['checks']['after']['valid'])

    def test_decimal_precision(self):
        tiny = Decimal('0.00000000000000000000000000001')
        t = {'tasks': [{'id': 'a', 'minutes': tiny}]}
        a = {'workers': 1, 'finish': tiny, 'schedule': [dict(task='a', worker=1, start=0, finish=tiny)]}
        b = {'workers': 1, 'finish': Decimal('0.00000000000000000000000000003'),
             'schedule': [dict(task='a', worker=1, start=Decimal('0.00000000000000000000000000002'),
                               finish=Decimal('0.00000000000000000000000000003'))]}
        r = p.compare(t, a, b, 1)
        self.assertEqual(r['finish_delta'], '0.00000000000000000000000000002')

    def test_worker_only(self):
        t, a, _ = p.demo()
        b = copy.deepcopy(a)
        for row in b['schedule']:
            row['worker'] = 2
        r = p.compare(t, a, b, 2)
        self.assertEqual(r['counts']['same_time'], 3)
        self.assertEqual(r['counts']['worker_moves'], 3)
        self.assertEqual(r['finish_delta'], '0')

    def test_mixed_directions(self):
        t = {'tasks': [{'id': x, 'minutes': 1} for x in ['a', 'b']]}
        a = {'workers': 1, 'finish': 2, 'schedule': [dict(task='a',worker=1,start=0,finish=1), dict(task='b',worker=1,start=1,finish=2)]}
        b = copy.deepcopy(a)
        b['schedule'][0]['task'], b['schedule'][1]['task'] = 'b', 'a'
        r = p.compare(t, a, b, 1)
        self.assertEqual(r['counts'], dict(earlier=1,later=1,same_time=0,worker_moves=0))
        self.assertEqual(r['finish_delta'], '0')

    def test_permutation_immutable(self):
        t, a, b = p.demo()
        saved = copy.deepcopy((t,a,b))
        r = p.compare(t,a,b,2)
        self.assertEqual((t,a,b),saved)
        t['tasks'].reverse(); a['schedule'].reverse(); b['schedule'].reverse()
        self.assertEqual(p.compare(t,a,b,2),r)

    def test_generated_delays(self):
        rng = random.Random(28)
        for _ in range(150):
            size, delay = rng.randint(1,20), rng.randint(0,100)
            tasks, rows, clock = [], [], 0
            for i in range(size):
                duration = rng.randint(1,10)
                tasks.append(dict(id=str(i),minutes=duration,after=[str(i-1)] if i else []))
                rows.append(dict(task=str(i),worker=1,start=clock,finish=clock+duration))
                clock += duration
            a = dict(workers=1,finish=clock,schedule=rows)
            b = copy.deepcopy(a); b['finish'] += delay
            for row in b['schedule']:
                row['start'] += delay; row['finish'] += delay
            r = p.compare(dict(tasks=tasks),a,b,1)
            self.assertTrue(r['comparable'])
            self.assertEqual(r['finish_delta'],str(delay))
            self.assertTrue(all(row['start_delta']==str(delay) for row in r['tasks']))

    def test_schema_refused(self):
        t,a,b=p.demo()
        with self.assertRaises(ValueError): p.compare(t,a,b,True)
        t['tasks'][0]['after']=['check']
        with self.assertRaises(ValueError): p.compare(t,a,b,2)

    def test_cli(self):
        root=Path('test/scratch/plancompare'); root.mkdir(parents=True,exist_ok=True)
        t,a,b=p.demo()
        for name,obj in [('tasks',t),('before',a),('after',b)]:
            (root/(name+'.json')).write_text(json.dumps(obj))
        cmd=[sys.executable,'-B',str(Path(p.__file__)), '--tasks',str(root/'tasks.json'), '--before',str(root/'before.json'), '--after',str(root/'after.json'),'--workers','2']
        r=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['finish_delta'],'-2')
        r=subprocess.run(cmd+['--budget','6'],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        (root/'after.json').write_text('{"workers":2,"workers":2}')
        r=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(r.returncode,1)
        self.assertIn('duplicate JSON key',r.stderr)


if __name__=='__main__': unittest.main()
