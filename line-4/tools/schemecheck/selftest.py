"""Offline transport, alternative-coverage and CLI regression tests."""
import copy
import itertools
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import schemecheck as s


def doc(policy=None, definition=None):
    return {'openapi': '3.1.0', 'paths': {'/a~b/c': {'get': {
        'responses': {'200': {'description': 'ok'}},
        'security': [{'a': []}] if policy is None else policy}}},
        'components': {'securitySchemes': {
            'a': {'type': 'apiKey', 'in': 'header', 'name': 'X-A'} if definition is None else definition,
            'b': {'type': 'http', 'scheme': 'bearer'}}}}


def changed(old, **fields):
    new = copy.deepcopy(old)
    new['components']['securitySchemes']['a'].update(fields)
    return new


def hits(old, new):
    return [f for f in s.compare(old, new)['findings'] if f['code'] == 'security_transport_incompatible']


class Tests(unittest.TestCase):
    def test_transport_matrix(self):
        # Independently model the wire slot and compare all 100 combinations.
        variants = [('header', 'X-A'), ('header', 'x-a'), ('header', 'X-B'),
                    ('query', 'X-A'), ('query', 'x-a'), ('cookie', 'X-A'),
                    ('cookie', 'x-a'), ('http', 'Basic'), ('http', 'basic'), ('http', 'bearer')]
        def make(item):
            place, name = item
            return doc(definition={'type': 'http', 'scheme': name} if place == 'http' else
                       {'type': 'apiKey', 'in': place, 'name': name})
        def wire(item):
            place, name = item
            return place, name.lower() if place in ('header', 'http') else name
        for a, b in itertools.product(variants, repeat=2):
            self.assertEqual(bool(hits(make(a), make(b))), wire(a) != wire(b), (a, b))

    def test_or_survivor_and_anonymous(self):
        old = doc([{'a': [], 'b': []}])
        new = changed(old, name='X-Other')
        new['paths']['/a~b/c']['get']['security'] = [{'a': []}, {'b': []}]
        self.assertFalse(hits(old, new))
        old = doc([{'a': []}, {'b': []}])
        self.assertTrue(hits(old, changed(old, name='X-Other')))
        old = doc([{}, {'a': []}])
        new = changed(old, name='X-Other')
        self.assertFalse(hits(old, new))

    def test_and_and_type_changes(self):
        old = doc([{'a': [], 'b': []}])
        self.assertTrue(hits(old, changed(old, name='X-B')))
        self.assertTrue(hits(doc(), changed(doc(), type='http', scheme='bearer')))
        self.assertTrue(hits(doc(), changed(doc(), type='mutualTLS')))

    def test_inherited_symbolic_break_not_duplicated(self):
        old, new = doc([]), doc()
        result = s.compare(old, new)
        self.assertEqual(result['counts']['breaking'], 1)
        self.assertIn('security_requirement_incompatible', {f['code'] for f in result['findings']})
        self.assertFalse(hits(old, new))

    def test_references_and_root_inheritance(self):
        old = doc()
        schemes = old['components']['securitySchemes']
        schemes['a/~'] = schemes.pop('a')
        schemes['a'] = {'$ref': '#/components/securitySchemes/a~1~0'}
        old['security'] = old['paths']['/a~b/c']['get'].pop('security')
        new = copy.deepcopy(old)
        new['components']['securitySchemes']['a/~']['in'] = 'cookie'
        self.assertTrue(hits(old, new))
        new['paths']['/a~b/c']['get']['security'] = []
        self.assertFalse(hits(old, new))

    def test_invalid_identical_effective_definitions(self):
        for definition in ({'type': 'apiKey'}, {'type': 'apiKey', 'in': 'body', 'name': 'x'},
                           {'type': 'apiKey', 'in': 'header', 'name': 'bad name'},
                           {'type': 'apiKey', 'in': 'header', 'name': 4},
                           {'type': 'http'}, {'type': 'http', 'scheme': ''},
                           {'type': 'http', 'scheme': 'bad scheme'}, {'type': 'http', 'scheme': 2}):
            old = doc(definition=definition)
            with self.subTest(definition=definition), self.assertRaises(s.api.Invalid):
                s.compare(old, old)
        # Redundant alternatives still validate; unused schemes are outside scope.
        old = doc([{}, {'a': []}], {'type': 'http'})
        with self.assertRaises(s.api.Invalid):
            s.compare(old, old)
        old = doc([], {'type': 'http'})
        self.assertEqual(s.compare(old, old)['findings'], [])

    def test_opaque_definition_changes_retain_review(self):
        for definition, fields in (
            ({'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'}, {'bearerFormat': 'opaque'}),
            ({'type': 'oauth2', 'flows': {}}, {'flows': {'clientCredentials': {}}}),
            ({'type': 'openIdConnect', 'openIdConnectUrl': 'https://example.invalid/a'},
             {'openIdConnectUrl': 'https://example.invalid/b'})):
            old = doc(definition=definition)
            new = changed(old, **fields)
            self.assertFalse(hits(old, new))
            self.assertEqual(s.compare(old, new)['status'], 'review_required')

    def test_determinism_locations_and_no_mutation(self):
        old = doc()
        new = changed(old, name='X-B')
        saved = copy.deepcopy((old, new))
        result = s.compare(old, new)
        self.assertEqual((old, new), saved)
        self.assertEqual(result, s.compare(json.loads(json.dumps(old, sort_keys=True)), new))
        self.assertEqual(hits(old, new)[0]['location'], '/paths/~1a~0b~1c/get/security')

    def test_limit(self):
        old = doc([{'a': []}] * 64)
        new = changed(old, name='X-Changed')
        for d in (old, new):
            op = d['paths']['/a~b/c']['get']
            d['paths'] = {'/p' + str(i): {'get': op} for i in range(25)}
        with self.assertRaisesRegex(s.api.Invalid, 'transport comparison limit'):
            s.compare(old, new)

    def test_real_capture_and_demo(self):
        result = s.demo()
        self.assertGreater(result['counts']['breaking'], 0)
        self.assertEqual(result['operations_compared'], 5)
        capture = s.auth.depend.unique.const.multiple.bound.BASE.with_name('imd-openapi.json')
        old, _ = s.api.load(capture)
        self.assertEqual(s.compare(old, old)['findings'], [])

    def test_cli_exits_and_hashes(self):
        root = Path('test/scratch')
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as tmp:
            a, b = Path(tmp) / 'a.json', Path(tmp) / 'b.json'
            a.write_text(json.dumps(doc()))
            script = str(Path(__file__).with_name('schemecheck.py'))
            for new, code in ((doc(), 0), (changed(doc(), name='X-B'), 1),
                              (changed(doc(), description='updated'), 3),
                              (changed(doc(), name=''), 2)):
                b.write_text(json.dumps(new))
                run = subprocess.run([sys.executable, '-B', script, 'compare', str(a), str(b)],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, code, run.stderr)
                if code != 2:
                    self.assertEqual(len(json.loads(run.stdout)['old_sha256']), 64)
            run = subprocess.run([sys.executable, '-B', script, 'demo'], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == '__main__':
    unittest.main()
