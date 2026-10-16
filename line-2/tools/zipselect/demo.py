#!/usr/bin/env python3
"""Select the genuine bundled public IMD capture; make no network requests."""
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
from zipselect import Rejected, local_path, process


def main():
    source = local_path(Path(__file__).resolve().parents[1] / 'safezip/imd-openapi.json')
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == 'be142840c010710cb2a5b9e5c73e71d8e79ec4054c15661699d60bfa627be96a'
    scratch = local_path('test/scratch')
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch, prefix='zipselect-demo-') as temporary:
        root = Path(temporary)
        archive_path = root / 'public-docs.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('docs/imd/openapi.json', payload)
            archive.writestr('notes/not-selected.txt', 'An inert demonstration note.\n')
            archive.writestr('unused-empty-directory/', b'')
        approved = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        options = dict(expected_sha256=approved, output_bytes=len(payload), seconds=10)
        try:
            process(archive_path, ['docs/imd/openapi.json'], root / 'refused',
                    output_nodes=2, **options)
        except Rejected as error:
            refusal = str(error)
            assert 'node limit' in refusal and not (root / 'refused').exists()
        else:
            raise AssertionError('accepted insufficient output-node budget')
        report = process(archive_path, ['docs/imd/openapi.json'], root / 'selected',
                         output_nodes=3, **options)
        assert (root / 'selected/docs/imd/openapi.json').read_bytes() == payload
        assert sorted(p.relative_to(root / 'selected').as_posix()
                      for p in (root / 'selected').rglob('*')) == [
                          'docs', 'docs/imd', 'docs/imd/openapi.json']
        assert not list(root.glob('.zipselect-*'))
        print(json.dumps({'ok': True, 'network_used': False,
                          'source': 'https://api.imd.fun/openapi.json',
                          'historical_public_capture_bytes': len(payload),
                          'selected_content_identical': True,
                          'unselected_paths_absent': True,
                          'small_node_budget_refused': refusal,
                          'report': report}, indent=2))


if __name__ == '__main__':
    main()
