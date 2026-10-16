#!/usr/bin/env python3
"""Compare two independently checked complete schedules; never execute tasks."""
import argparse
from decimal import Decimal
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location('plancompare_check', Path(__file__).resolve().parents[1] / 'plancheck' / 'plancheck.py')
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def exact(value):
    """Render a finite decimal Fraction without float rounding or context loss."""
    value = Fraction(value)
    sign = '-' if value < 0 else ''
    n, d = abs(value.numerator), value.denominator
    whole, rest = divmod(n, d)
    digits = []
    while rest:
        rest *= 10
        digit, rest = divmod(rest, d)
        digits.append(str(digit))
    return sign + str(whole) + ('.' + ''.join(digits) if digits else '')


def compare(tasks, before, after, workers, budget=None):
    """Same graph, estimates, capacity and optional deadline for both plans.

    If either fails feasibility, return diagnostics only: never compare invalid
    intervals. A deadline failure is also a failed check, not a feasible revision.
    """
    checks = {name: check.check(tasks, plan, workers, budget)
              for name, plan in (('before', before), ('after', after))}
    if not all(report['valid'] for report in checks.values()):
        return {'comparable': False, 'checks': checks}
    def index(plan):
        return {r['task']: (r['worker'], check.number(r['start'], 'start'),
                            check.number(r['finish'], 'finish')) for r in plan['schedule']}
    old, new = index(before), index(after)
    changes = []
    counts = {'earlier': 0, 'later': 0, 'same_time': 0, 'worker_moves': 0}
    for task in sorted(old):
        ow, os, oe = old[task]
        nw, ns, ne = new[task]
        delta = ns - os
        timing = 'earlier' if delta < 0 else 'later' if delta > 0 else 'same_time'
        counts[timing] += 1
        counts['worker_moves'] += ow != nw
        changes.append({'task': task, 'timing': timing, 'start_delta': exact(delta),
                        'finish_delta': exact(ne - oe), 'before_worker': ow,
                        'after_worker': nw, 'worker_changed': ow != nw})
    old_finish = max(r[2] for r in old.values())
    new_finish = max(r[2] for r in new.values())
    result = {'comparable': True, 'units': 'minutes', 'checks': checks,
              'before_finish': exact(old_finish), 'after_finish': exact(new_finish),
              'finish_delta': exact(new_finish - old_finish), 'counts': counts,
              'tasks': changes,
              'scope': 'same full job and estimates; deltas are after minus before; no execution, progress or optimality claim'}
    if budget is not None:
        deadline = check.number(budget, 'budget')
        result['before_deadline_margin'] = exact(deadline - old_finish)
        result['after_deadline_margin'] = exact(deadline - new_finish)
    return result


def demo():
    tasks = {'tasks': [{'id': 'build', 'minutes': 4}, {'id': 'fixtures', 'minutes': 2},
                       {'id': 'check', 'minutes': 1, 'after': ['build', 'fixtures']}]}
    before = {'workers': 2, 'finish': 7, 'schedule': [
        {'task': 'build', 'worker': 1, 'start': 0, 'finish': 4},
        {'task': 'fixtures', 'worker': 1, 'start': 4, 'finish': 6},
        {'task': 'check', 'worker': 1, 'start': 6, 'finish': 7}]}
    after = {'workers': 2, 'finish': 5, 'schedule': [
        {'task': 'build', 'worker': 1, 'start': 0, 'finish': 4},
        {'task': 'fixtures', 'worker': 2, 'start': 0, 'finish': 2},
        {'task': 'check', 'worker': 1, 'start': 4, 'finish': 5}]}
    return tasks, before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true')
    parser.add_argument('--tasks')
    parser.add_argument('--before')
    parser.add_argument('--after')
    parser.add_argument('--workers', type=int)
    parser.add_argument('--budget', type=Decimal)
    args = parser.parse_args()
    try:
        if args.demo:
            if any(v is not None for v in (args.tasks, args.before, args.after, args.workers, args.budget)):
                raise ValueError('--demo cannot be combined with other options')
            result = compare(*demo(), workers=2, budget=8)
        else:
            if any(v is None for v in (args.tasks, args.before, args.after, args.workers)):
                raise ValueError('--tasks, --before, --after and --workers are required')
            result = compare(check.read_json(args.tasks), check.read_json(args.before),
                             check.read_json(args.after), args.workers, args.budget)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0 if result['comparable'] else 2
    except (ValueError, OSError, RecursionError, OverflowError) as exc:
        print('plancompare: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
