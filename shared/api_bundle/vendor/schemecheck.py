#!/usr/bin/env python3
"""Offline OpenAPI security transport changes; Python standard library only."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys

PREVIOUS = Path(__file__).with_name('authcheck.py')
spec = importlib.util.spec_from_file_location('schemecheck_auth', PREVIOUS)
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)
api = auth.api
TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z", re.ASCII)


def transport(document, name):
    """Validate the supported transport fields of an effective named scheme."""
    scheme = document.resolve(document.obj['components']['securitySchemes'][name])
    kind = scheme['type']  # AuthCheck already validates the type and reference.
    if kind == 'apiKey':
        place, label = scheme.get('in'), scheme.get('name')
        api.require(place in ('header', 'query', 'cookie'), 'apiKey in must be header, query or cookie')
        api.require(isinstance(label, str) and bool(label), 'apiKey name must be nonempty')
        if place == 'header':
            api.require(TOKEN.fullmatch(label) is not None, 'apiKey header name must be an HTTP token')
            label = label.lower()
        return kind, place, label
    if kind == 'http':
        label = scheme.get('scheme')
        api.require(isinstance(label, str) and TOKEN.fullmatch(label) is not None,
                    'http scheme must be an HTTP token')
        return kind, label.lower()
    # OAuth flows, discovery, TLS trust and actual credential acceptance are
    # unresolved. Keep inherited document reviews rather than guessing equivalence.
    return (kind,)


class Analyzer(auth.Analyzer):
    def __init__(self, old, new):
        super().__init__(old, new)
        self.transports = {}
        self.transport_comparisons = 0

    def identity(self, side, name):
        key = side, name
        if key not in self.transports:
            self.transports[key] = transport(self.old if side == 'old' else self.new, name)
        return self.transports[key]

    def operation(self, path, method, old_item, new_item):
        super().operation(path, method, old_item, new_item)
        before = auth.policy(self.old, old_item[method])
        after = auth.policy(self.new, new_item[method])
        # Validate all effective definitions, even in redundant alternatives.
        for side, policies in (('old', before), ('new', after)):
            for _, _, option in policies:
                for name in option:
                    self.identity(side, name)
        loc = api.pointer('/paths', path) + '/' + method + '/security'
        for index, source, _ in before:
            symbolic_cover = False
            transport_cover = False
            for _, target, option in after:
                self.transport_comparisons += 1
                api.require(self.transport_comparisons <= auth.MAX_COMPARISONS,
                            'transport comparison limit exceeded (100000)')
                if target <= source:
                    symbolic_cover = True
                    if all(self.identity('old', name) == self.identity('new', name) for name in option):
                        transport_cover = True
                        break
            if symbolic_cover and not transport_cover:
                self.emit('breaking', 'security_transport_incompatible', loc,
                          'Old effective alternative ' + str(index) +
                          ' has no new alternative preserving both its obligations and declared '
                          'scheme type, API-key location/name or HTTP authentication scheme. '
                          'Existing request construction may fail; no credential was tested.')


def compare(old, new):
    analyzer = Analyzer(old, new)
    result = analyzer.run()
    result['extension'] = 'schemecheck-v1 (includes authcheck and all earlier line 4 analyzers)'
    result['security_alternative_comparisons'] = analyzer.auth_comparisons
    result['security_transport_comparisons'] = analyzer.transport_comparisons
    return result


def demo():
    capture = Path(__file__).resolve().parents[1] / 'imd-openapi.json'
    old, digest = api.load(capture)
    new = copy.deepcopy(old)
    schemes = new['components']['securitySchemes']
    names = sorted(name for name, value in schemes.items() if value.get('type') == 'http')
    api.require(bool(names), 'demo capture has no HTTP scheme')
    schemes[names[0]]['scheme'] = 'basic' if schemes[names[0]]['scheme'].lower() != 'basic' else 'bearer'
    report = compare(old, new)
    api.require(report['counts']['breaking'] > 0, 'demo did not detect its hypothetical transport change')
    report.update(capture_sha256=digest, baseline_source='https://api.imd.fun/openapi.json',
                  demo='Hypothetically change the captured HTTP Bearer scheme to Basic; no API operation called.')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('demo')
    diff = commands.add_parser('compare')
    diff.add_argument('old')
    diff.add_argument('new')
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            result = demo()
        else:
            old, oh = api.load(args.old)
            new, nh = api.load(args.new)
            result = compare(old, new)
            result.update(old_sha256=oh, new_sha256=nh)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if args.command == 'demo' else {
            'breaking': 1, 'review_required': 3, 'no_detected_breakage': 0}[result['status']]
    except (api.Invalid, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print('schemecheck: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
