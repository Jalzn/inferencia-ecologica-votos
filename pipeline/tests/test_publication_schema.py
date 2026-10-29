"""An internally checksummed release must still satisfy the complete geometry schema."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import jsonschema

from elections.export.verify import validate_release

FIXTURE = Path(__file__).parents[2] / 'data/fixtures/public'


class PublicationSchemaTests(unittest.TestCase):
    def test_schema_rejects_malformed_state_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            release = Path(temp) / 'release'
            shutil.copytree(FIXTURE, release)
            manifest = json.loads((release / 'manifest.json').read_text())
            descriptor = manifest['resources']['states']['MG']
            resource = release / descriptor['path']
            bundle = json.loads(gzip.decompress(resource.read_bytes()))
            collection = bundle['geometry']['municipalities']
            collection['features'][0]['geometry'] = 'not a geometry object'
            content = gzip.compress(json.dumps(bundle, ensure_ascii=False).encode(), mtime=0)
            resource.write_bytes(content)
            descriptor['bytes'] = len(content)
            descriptor['sha256'] = hashlib.sha256(content).hexdigest()
            (release / 'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaises(jsonschema.ValidationError):
                validate_release(release, deep_schema=True)


if __name__ == '__main__':
    unittest.main()
