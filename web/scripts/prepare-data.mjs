import { access, cp, mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const target = path.join(root, 'public', 'data');
try {
  await access(path.join(target, 'manifest.json'));
  const manifest = JSON.parse(await readFile(path.join(target, 'manifest.json'), 'utf8'));
  console.log(`Using existing ${manifest.scope} dataset: ${manifest.datasetVersion}`);
  if (manifest.schemaVersion !== '2.0')
    console.warn(
      `Warning: public/data uses schema ${manifest.schemaVersion}; the explorer requires 2.0. ` +
        'Regenerate the release, or remove public/data to stage the fixture.',
    );
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
  const source = path.resolve(root, '..', 'data', 'fixtures', 'public');
  await access(path.join(source, 'manifest.json'));
  await mkdir(target, { recursive: true });
  await cp(source, target, { recursive: true });
  console.log(
    'Staged the real-data development fixture. Its limited coverage is disclosed in the UI.',
  );
}
