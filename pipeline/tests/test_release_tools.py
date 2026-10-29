"""Exercise publication boundaries and untrusted archive handling."""
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('release_tools', Path(__file__).parents[2] / 'scripts/release_tools.py')
release_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_tools)


class ReleaseToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.write_manifest('full')

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, scope):
        (self.source / 'manifest.json').write_text(json.dumps({
            'schemaVersion': '2.0', 'datasetVersion': 'test-release', 'scope': scope,
            'provenance': {'runId': 'test-run', 'resultsSha256': '1' * 64, 'panelSha256': '2' * 64,
                           'code': {'gitRevision': '0' * 40, 'dirty': False},
                           'exportCode': {'gitRevision': '0' * 40, 'dirty': False}}}))

    def test_round_trip_is_deterministic_and_preserves_content(self):
        (self.source / 'observations.json').write_text('{"observed":42}')
        first = release_tools.pack_release(self.source, self.root / 'first.tar.gz')
        second = release_tools.pack_release(self.source, self.root / 'second.tar.gz')
        self.assertEqual(first['sha256'], second['sha256'])
        self.assertEqual(Path(first['checksumPath']).read_text(), f"{first['sha256']}  first.tar.gz\n")
        target = self.root / 'restored'
        release_tools.restore_archive(Path(first['path']), target, first['sha256'])
        self.assertEqual((target / 'observations.json').read_bytes(), (self.source / 'observations.json').read_bytes())

    def test_fixture_cannot_be_packaged_as_full_release(self):
        self.write_manifest('fixture')
        with self.assertRaisesRegex(ValueError, 'fixture'):
            release_tools.pack_release(self.source, self.root / 'fixture.tar.gz')

    def test_dirty_or_missing_code_provenance_cannot_be_packaged(self):
        original = json.loads((self.source / 'manifest.json').read_text())
        for field in ('code', 'exportCode'):
            for value in ({'gitRevision': '0' * 40, 'dirty': True}, {}):
                with self.subTest(field=field, value=value):
                    manifest = json.loads(json.dumps(original))
                    manifest['provenance'][field] = value
                    (self.source / 'manifest.json').write_text(json.dumps(manifest))
                    target = self.root / 'rejected.tar.gz'
                    with self.assertRaisesRegex(ValueError, 'clean, committed'):
                        release_tools.pack_release(self.source, target)
                    self.assertFalse(target.exists())

    def test_registered_artifact_is_portable_and_version_cannot_be_reassigned(self):
        package = release_tools.pack_release(self.source, self.root / 'release.tar.gz')
        index = self.root / 'releases.json'
        entry = release_tools.register_release(self.source, package, index)
        self.assertEqual(entry['archive']['path'], 'release.tar.gz')
        self.assertEqual(entry['archive']['sha256'], package['sha256'])
        self.assertNotIn('url', entry)
        release_tools.register_release(self.source, package, index)
        self.assertEqual(len(json.loads(index.read_text())['releases']), 1)
        (self.source / 'changed.json').write_text('{}')
        different = release_tools.pack_release(self.source, self.root / 'different.tar.gz')
        original_index = index.read_bytes()
        with self.assertRaisesRegex(ValueError, 'already registered'):
            release_tools.register_release(self.source, different, index)
        self.assertEqual(index.read_bytes(), original_index)

    def test_local_restore_cli_verifies_archive_and_recovers_files(self):
        (self.source / 'observations.json').write_text('{"observed":42}')
        package = release_tools.pack_release(self.source, self.root / 'release.tar.gz')
        target = self.root / 'restored'
        result = subprocess.run([sys.executable, str(SPEC.origin), 'restore', '--archive', package['path'],
                                 '--sha256', package['sha256'], '--output', str(target)],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(result.stdout)['datasetVersion'], 'test-release')
        self.assertEqual((target / 'observations.json').read_text(), '{"observed":42}')

    def test_wrong_hash_does_not_create_destination(self):
        result = release_tools.pack_release(self.source, self.root / 'release.tar.gz')
        target = self.root / 'restored'
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            release_tools.restore_archive(Path(result['path']), target, '0' * 64)
        self.assertFalse(target.exists())

    def test_traversal_and_symbolic_links_are_rejected(self):
        for name, link in [('../escaped.txt', False), ('linked', True)]:
            with self.subTest(name=name):
                archive_path = self.root / ('link.tar.gz' if link else 'traversal.tar.gz')
                with tarfile.open(archive_path, 'w:gz') as archive:
                    info = tarfile.TarInfo(name)
                    if link:
                        info.type = tarfile.SYMTYPE
                        info.linkname = '/tmp'
                        archive.addfile(info)
                    else:
                        info.size = 4
                        archive.addfile(info, io.BytesIO(b'test'))
                target = self.root / 'rejected'
                with self.assertRaises(ValueError):
                    release_tools.restore_archive(archive_path, target, release_tools.sha256(archive_path))
                self.assertFalse(target.exists())
                self.assertFalse((self.root / 'escaped.txt').exists())


if __name__ == '__main__':
    unittest.main()
