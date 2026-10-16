#!/usr/bin/env python3
"""Extract an exact file allowlist from an approved, fully checked ZIP."""
import argparse
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'zipgate'))
from zipgate import Rejected, local_path, positive, process as gate_process


def process(archive_path, selected, output=None, *, expected_sha256,
            output_nodes=32000, output_bytes=67108864, entries=1000,
            directory_bytes=2097152, archive_bytes=33554432, nodes=32000,
            file_bytes=16777216, total_bytes=67108864, ratio=200,
            seconds=None, cancelled=None):
    """Plan or publish only exact named files; validate every archive member.

    All paths are confined to cwd. No recursive directory or glob selection.
    Gate/SafeZip first check all payloads, including omitted ones. A second
    bounded snapshot must match that approved digest before it is parsed.
    """
    positive('entries', entries)
    positive('output_nodes', output_nodes)
    positive('output_bytes', output_bytes)
    if not isinstance(expected_sha256, str) or not re.fullmatch(
            r'[0-9a-fA-F]{64}', expected_sha256):
        raise Rejected('an approved 64-hex archive SHA-256 is required')
    if not isinstance(selected, (list, tuple)) or not selected or len(selected) > entries:
        raise Rejected('selection must be a nonempty list/tuple within entry limit')
    names = set()
    for name in selected:
        if not isinstance(name, str) or not name or len(name) > 1024:
            raise Rejected('selection must contain bounded, nonempty path strings')
        if name in names:
            raise Rejected('duplicate selected path')
        names.add(name)
    if seconds is not None:
        try:
            valid = (not isinstance(seconds, bool) and isinstance(seconds, (int, float))
                     and math.isfinite(seconds) and seconds > 0)
        except OverflowError:
            valid = False
        if not valid:
            raise Rejected('seconds must be a finite positive number')
    if cancelled is not None and not callable(cancelled):
        raise Rejected('cancelled must be callable')
    started = time.monotonic()

    def checkpoint():
        if cancelled is not None and cancelled():
            raise Rejected('operation cancelled')
        if seconds is not None and time.monotonic() - started >= seconds:
            raise Rejected('operation time budget exceeded')
        return False

    checkpoint()
    source = local_path(archive_path)
    target = local_path(output) if output is not None else None
    if target is not None:
        if target.exists() or not target.parent.is_dir():
            raise Rejected('output must be absent with an existing parent')
    checked = gate_process(source, expected_sha256=expected_sha256,
                           entries=entries, directory_bytes=directory_bytes,
                           archive_bytes=archive_bytes, nodes=nodes,
                           file_bytes=file_bytes, total_bytes=total_bytes,
                           ratio=ratio, cancelled=checkpoint)
    inventory = {entry['path']: entry for entry in checked['entries']}
    chosen, required_nodes, size = [], set(), 0
    for name in sorted(names):
        checkpoint()
        entry = inventory.get(name)
        if entry is None or entry['kind'] != 'file':
            raise Rejected('selection is not an exact file path: ' + repr(name))
        chosen.append(dict(entry))
        parts = name.split('/')
        for index in range(1, len(parts) + 1):
            required_nodes.add('/'.join(parts[:index]))
            if len(required_nodes) > output_nodes:
                raise Rejected('selected output node limit exceeded')
        size += entry['bytes']
        if size > output_bytes:
            raise Rejected('selected output byte limit exceeded')
    report = {'ok': True, 'mode': 'extract' if target is not None else 'plan',
              'archive_sha256': checked['archive_sha256'],
              'all_archive_payloads_checked': True, 'preflight': checked['preflight'],
              'archive_entries': len(inventory), 'archive_total_bytes': checked['total_bytes'],
              'selected_files': len(chosen), 'output_nodes': len(required_nodes),
              'output_bytes': size, 'entries': chosen}
    checkpoint()
    if target is None:
        return report

    # Bind the second parser and output bytes to the exact gated archive.
    snapshot = io.BytesIO()
    digest, captured = hashlib.sha256(), 0
    stage = None
    try:
        with source.open('rb') as reader:
            if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
                raise Rejected('archive must be regular')
            while True:
                checkpoint()
                chunk = reader.read(min(65536, archive_bytes - captured + 1))
                if not chunk:
                    break
                captured += len(chunk)
                if captured > archive_bytes:
                    raise Rejected('archive byte limit exceeded during selected snapshot')
                digest.update(chunk)
                snapshot.write(chunk)
        if not hmac.compare_digest(digest.hexdigest(), checked['archive_sha256']):
            raise Rejected('archive changed after review')
        checkpoint()
        snapshot.seek(0)
        with zipfile.ZipFile(snapshot) as archive:
            checkpoint()
            stage = Path(tempfile.mkdtemp(prefix='.zipselect-', dir=target.parent))
            for entry in chosen:
                checkpoint()
                name = entry['path']
                destination = stage / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                count, payload_hash = 0, hashlib.sha256()
                with archive.open(name) as reader, destination.open('xb') as writer:
                    while True:
                        checkpoint()
                        # Detect growth without writing a byte past reviewed size.
                        chunk = reader.read(min(65536, entry['bytes'] - count + 1))
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > entry['bytes']:
                            raise Rejected('selected file exceeds reviewed size')
                        payload_hash.update(chunk)
                        writer.write(chunk)
                if count != entry['bytes'] or payload_hash.hexdigest() != entry['sha256']:
                    raise Rejected('selected file differs from reviewed content')
        checkpoint()
        if target.exists() or target.is_symlink():
            raise Rejected('output appeared during extraction')
        stage.rename(target)
        stage = None
        return report
    finally:
        snapshot.close()
        if stage is not None:
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('plan', 'extract'))
    parser.add_argument('archive_path')
    parser.add_argument('output', nargs='?')
    parser.add_argument('--file', dest='selected', action='append', required=True,
                        help='exact case-sensitive archive file path; repeatable')
    parser.add_argument('--sha256', dest='expected_sha256', required=True)
    for name, default in [('output-nodes', 32000), ('output-bytes', 67108864),
                          ('entries', 1000), ('directory-bytes', 2097152),
                          ('archive-bytes', 33554432), ('nodes', 32000),
                          ('file-bytes', 16777216), ('total-bytes', 67108864), ('ratio', 200)]:
        parser.add_argument('--' + name, type=int, default=default)
    parser.add_argument('--seconds', type=float)
    args = vars(parser.parse_args())
    command = args.pop('command')
    if (command == 'extract') != (args['output'] is not None):
        parser.error('extract requires output; plan takes no output')
    try:
        report = process(**args)
    except (ValueError, OSError, zipfile.BadZipFile, NotImplementedError,
            RuntimeError, EOFError, zlib.error) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
