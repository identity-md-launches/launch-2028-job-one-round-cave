#!/usr/bin/env python3
"""Adversarial offline checks in disposable workspace directories; no sleeps."""
import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zipselect as zs


class SelectionTests(unittest.TestCase):
    def setUp(self):
        scratch = zs.local_path('test/scratch')
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch, prefix='zipselect-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive = self.root / 'input.zip'
        self.target = self.root / 'output'
        self.pack([('docs/a.txt', b'alpha'), ('docs/b.txt', b'beta'), ('empty/', b'')])

    def pack(self, pairs, compression=zipfile.ZIP_DEFLATED):
        with zipfile.ZipFile(self.archive, 'w', compression=compression) as archive:
            for name, payload in pairs:
                archive.writestr(name, payload)
        self.approved = hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def run_selection(self, selected=None, **options):
        return zs.process(self.archive, selected if selected is not None else ['docs/a.txt'],
                          self.target, expected_sha256=self.approved, **options)

    def assert_clean(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.zipselect-*')), [])
        self.assertEqual(list(self.root.glob('.safezip-*')), [])

    def test_exact_file_and_implicit_parents(self):
        report = self.run_selection(output_nodes=2, output_bytes=5)
        self.assertEqual((self.target / 'docs/a.txt').read_bytes(), b'alpha')
        self.assertEqual(sorted(p.relative_to(self.target).as_posix()
                                for p in self.target.rglob('*')), ['docs', 'docs/a.txt'])
        self.assertEqual(report['output_nodes'], 2)
        self.assertEqual(report['output_bytes'], 5)
        self.assertEqual(report['archive_entries'], 3)
        self.assertTrue(report['all_archive_payloads_checked'])

    def test_sorted_files_shared_parents(self):
        report = self.run_selection(['docs/b.txt', 'docs/a.txt'], output_nodes=3)
        self.assertEqual(report['output_nodes'], 3)
        self.assertEqual([x['path'] for x in report['entries']], ['docs/a.txt', 'docs/b.txt'])

    def test_plan_writes_nothing(self):
        before = sorted(self.root.iterdir())
        result = zs.process(self.archive, ['docs/a.txt'], expected_sha256=self.approved)
        self.assertEqual(result['mode'], 'plan')
        self.assertEqual(before, sorted(self.root.iterdir()))

    def test_selection_is_literal(self):
        for name in ['docs/*', 'docs', 'docs/', 'empty', 'empty/', 'DOCS/a.txt',
                     './docs/a.txt', '../docs/a.txt', '/docs/a.txt', 'missing']:
            with self.subTest(name=name), self.assertRaises(zs.Rejected):
                self.run_selection([name])
            self.assert_clean()

    def test_invalid_selection_types(self):
        for selection in [[], (), 'docs/a.txt', {'docs/a.txt'}, [1], [''], [None],
                          ['docs/a.txt', 'docs/a.txt'], ['x' * 1025]]:
            with self.subTest(selection=selection), self.assertRaises(zs.Rejected):
                zs.process(self.archive, selection, self.target, expected_sha256=self.approved)
            self.assert_clean()

    def test_required_approval(self):
        for digest in [None, '', 'g' * 64, '0' * 63, '0' * 64, 1]:
            with self.subTest(digest=digest), self.assertRaises(zs.Rejected):
                zs.process(self.archive, ['docs/a.txt'], self.target, expected_sha256=digest)
            self.assert_clean()

    def test_uppercase_approval_and_tuple(self):
        result = zs.process(self.archive, ('docs/a.txt',), self.target,
                            expected_sha256=self.approved.upper())
        self.assertEqual(result['archive_sha256'], self.approved)

    def test_node_budget(self):
        with self.assertRaisesRegex(zs.Rejected, 'node limit'):
            self.run_selection(output_nodes=1)
        self.assert_clean()

    def test_byte_budget(self):
        with self.assertRaisesRegex(zs.Rejected, 'byte limit'):
            self.run_selection(output_bytes=4)
        self.assert_clean()

    def test_zero_length_file(self):
        self.pack([('zero', b'')], zipfile.ZIP_STORED)
        result = self.run_selection(['zero'], output_nodes=1, output_bytes=1)
        self.assertEqual(result['output_bytes'], 0)
        self.assertEqual((self.target / 'zero').read_bytes(), b'')

    def test_invalid_limits(self):
        for key in ['output_nodes', 'output_bytes', 'entries', 'archive_bytes', 'nodes',
                    'directory_bytes', 'total_bytes', 'file_bytes', 'ratio']:
            for value in [True, 0, -1, 1.5, float('nan'), '2']:
                with self.subTest(key=key, value=value), self.assertRaises(zs.Rejected):
                    self.run_selection(**{key: value})
                self.assert_clean()

    def test_unselected_traversal_is_rejected(self):
        self.pack([('docs/a.txt', b'alpha'), ('../escape', b'no')])
        with self.assertRaises(zs.Rejected):
            self.run_selection()
        self.assert_clean()

    def test_unselected_symlink_is_rejected(self):
        info = zipfile.ZipInfo('link')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.pack([('docs/a.txt', b'alpha'), (info, b'elsewhere')])
        with self.assertRaises(zs.Rejected):
            self.run_selection()
        self.assert_clean()

    def test_unselected_case_collision_is_rejected(self):
        self.pack([('docs/a.txt', b'alpha'), ('DOCS/b.txt', b'other')])
        with self.assertRaises(zs.Rejected):
            self.run_selection()
        self.assert_clean()

    def test_unselected_corrupt_payload_is_rejected(self):
        self.pack([('docs/a.txt', b'alpha'), ('other', b'unselected-payload')], zipfile.ZIP_STORED)
        data = bytearray(self.archive.read_bytes())
        index = data.index(b'unselected-payload')
        data[index] ^= 1
        self.archive.write_bytes(data)
        self.approved = hashlib.sha256(data).hexdigest()
        with self.assertRaises(zipfile.BadZipFile):
            self.run_selection()
        self.assert_clean()

    def test_unselected_resource_limit_is_enforced(self):
        self.pack([('docs/a.txt', b'alpha'), ('other', b'123456')])
        with self.assertRaisesRegex(zs.Rejected, 'individual file'):
            self.run_selection(file_bytes=5)
        self.assert_clean()

    def test_directory_gate_runs_before_parser(self):
        with mock.patch.object(zs.zipfile, 'ZipFile', side_effect=AssertionError('parser called')):
            with self.assertRaisesRegex(zs.Rejected, 'directory byte limit'):
                self.run_selection(directory_bytes=1)
        self.assert_clean()

    def test_archive_replacement_before_second_parser(self):
        original = zs.gate_process
        real_parser = zipfile.ZipFile
        calls = []

        def reviewed(*args, **kwargs):
            result = original(*args, **kwargs)
            self.archive.write_bytes(b'changed after review')
            return result

        def parser(*args, **kwargs):
            calls.append(1)
            return real_parser(*args, **kwargs)

        with mock.patch.object(zs, 'gate_process', reviewed), mock.patch.object(
                zs.zipfile, 'ZipFile', parser):
            with self.assertRaisesRegex(zs.Rejected, 'changed after review'):
                self.run_selection()
        self.assertEqual(len(calls), 1)
        self.assert_clean()

    def test_archive_growth_between_phases(self):
        original = zs.gate_process
        limit = self.archive.stat().st_size

        def grow(*args, **kwargs):
            result = original(*args, **kwargs)
            self.archive.write_bytes(b'x' * (limit + 1))
            return result

        with mock.patch.object(zs, 'gate_process', grow):
            with self.assertRaisesRegex(zs.Rejected, 'byte limit'):
                self.run_selection(archive_bytes=limit)
        self.assert_clean()

    def test_cancelled_stage_is_removed(self):
        def stop():
            return bool(list(self.root.glob('.zipselect-*')))

        with self.assertRaisesRegex(zs.Rejected, 'cancelled'):
            self.run_selection(cancelled=stop)
        self.assert_clean()

    def test_partial_output_failure_is_removed(self):
        original = zipfile.ZipFile.open
        calls = []

        def broken(archive, name, *args, **kwargs):
            # Gate reads ZipInfo objects; only selected extraction opens names.
            if isinstance(name, str):
                calls.append(name)
                if name == 'docs/b.txt':
                    raise OSError('simulated read failure after first output')
            return original(archive, name, *args, **kwargs)

        with mock.patch.object(zs.zipfile.ZipFile, 'open', broken):
            with self.assertRaisesRegex(OSError, 'simulated read failure'):
                self.run_selection(['docs/a.txt', 'docs/b.txt'])
        self.assertEqual(calls, ['docs/a.txt', 'docs/b.txt'])
        self.assert_clean()

    def test_selected_stream_size_and_hash_are_rechecked(self):
        original = zipfile.ZipFile.open
        for changed in [b'ALPHA', b'alph', b'alpha!']:
            def replace_stream(archive, name, *args, **kwargs):
                if isinstance(name, str):
                    return io.BytesIO(changed)
                return original(archive, name, *args, **kwargs)

            with self.subTest(changed=changed), mock.patch.object(
                    zs.zipfile.ZipFile, 'open', replace_stream):
                with self.assertRaises(zs.Rejected):
                    self.run_selection()
            self.assert_clean()

    def test_selected_snapshot_survives_path_replacement_after_capture(self):
        original = zipfile.ZipFile
        calls = []

        def parse(snapshot, *args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                self.archive.write_bytes(b'pathname replaced after selected capture')
            return original(snapshot, *args, **kwargs)

        with mock.patch.object(zs.zipfile, 'ZipFile', parse):
            report = self.run_selection()
        self.assertEqual(len(calls), 2)
        self.assertEqual(report['archive_sha256'], self.approved)
        self.assertEqual((self.target / 'docs/a.txt').read_bytes(), b'alpha')

    def test_selected_byte_budget_is_aggregate(self):
        with self.assertRaisesRegex(zs.Rejected, 'byte limit'):
            self.run_selection(['docs/a.txt', 'docs/b.txt'], output_bytes=8)
        self.assert_clean()

    def test_deadline_shared_across_review_and_publication(self):
        original = zs.gate_process
        clock = [100.0]

        def expire(*args, **kwargs):
            result = original(*args, **kwargs)
            clock[0] = 102.0
            return result

        with mock.patch.object(zs.time, 'monotonic', lambda: clock[0]), mock.patch.object(
                zs, 'gate_process', expire):
            with self.assertRaisesRegex(zs.Rejected, 'time budget'):
                self.run_selection(seconds=1)
        self.assert_clean()

    def test_invalid_deadline_and_callback(self):
        for value in [True, 0, -1, '1', float('inf'), float('nan'), 10 ** 1000]:
            with self.subTest(value=repr(value)), self.assertRaises(zs.Rejected):
                self.run_selection(seconds=value)
        with self.assertRaises(zs.Rejected):
            self.run_selection(cancelled=True)
        self.assert_clean()

    def test_existing_output_preserved(self):
        self.target.mkdir()
        marker = self.target / 'keep'
        marker.write_bytes(b'unchanged')
        with self.assertRaises(zs.Rejected):
            self.run_selection()
        self.assertEqual(marker.read_bytes(), b'unchanged')
        self.assertEqual(list(self.root.glob('.zipselect-*')), [])

    def test_output_symlink_rejected(self):
        self.target.symlink_to(self.root / 'absent', target_is_directory=True)
        with self.assertRaises(zs.Rejected):
            self.run_selection()
        self.assertTrue(self.target.is_symlink())
        self.assertFalse((self.root / 'absent').exists())

    def test_paths_outside_workspace_rejected(self):
        with self.assertRaises(zs.Rejected):
            zs.process('/outside-workspace.zip', ['a'], expected_sha256=self.approved)
        with self.assertRaises(zs.Rejected):
            zs.process(self.archive, ['docs/a.txt'], '/outside-workspace-output',
                       expected_sha256=self.approved)
        self.assert_clean()

    def test_cli_plan_extract_and_refusal(self):
        base = [sys.executable, '-B', str(Path(zs.__file__)), 'plan', str(self.archive),
                '--sha256', self.approved, '--file', 'docs/a.txt']
        result = subprocess.run(base, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)['mode'], 'plan')
        extract = base[:]
        extract[3] = 'extract'
        extract.insert(5, str(self.target))
        result = subprocess.run(extract, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual((self.target / 'docs/a.txt').read_bytes(), b'alpha')
        result = subprocess.run(base[:-1] + ['missing'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(result.stdout)['ok'])
        result = subprocess.run(base[:5] + ['--file', 'docs/a.txt'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
