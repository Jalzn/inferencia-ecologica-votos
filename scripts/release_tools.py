"""Package and restore an immutable public dataset without using Git for large files."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen

MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_EXPANDED_BYTES = 1_000_000_000


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check_manifest(directory: Path, require_full: bool = True) -> dict:
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('schemaVersion') != '2.0':
        raise ValueError('Unsupported dataset schema version')
    if require_full and manifest.get('scope') != 'full':
        raise ValueError('A fixture dataset cannot be published as a complete release')
    if require_full:
        for field in ('code', 'exportCode'):
            code = manifest.get('provenance', {}).get(field, {})
            if not code.get('gitRevision') or code.get('dirty') is not False:
                raise ValueError('A complete release requires clean, committed analysis and export code')
    return manifest


def pack_release(directory: Path, output: Path) -> dict:
    directory = directory.resolve()
    check_manifest(directory)
    checksum_path = output.with_name(output.name + '.sha256')
    for target in (output, checksum_path):
        if target.exists():
            raise FileExistsError(f'Refusing to replace {target}')
    if output.resolve().is_relative_to(directory):
        raise ValueError('The archive must be outside its input directory')
    files = sorted(p for p in directory.rglob('*') if p.is_file())
    if any(p.is_symlink() or not p.resolve().is_relative_to(directory) for p in files):
        raise ValueError('Release files must not be symbolic links')
    total = sum(p.stat().st_size for p in files)
    if total > MAX_EXPANDED_BYTES:
        raise ValueError('Public data exceeds the configured static-site size budget')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target:
        with gzip.GzipFile(fileobj=target, mode='wb', filename='', mtime=0, compresslevel=1) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for path in files:
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(directory).as_posix())
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    info.mode = 0o644
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
    checksum = sha256(output)
    checksum_path.write_text(f'{checksum}  {output.name}\n')
    return {'path': str(output), 'sha256': checksum, 'bytes': output.stat().st_size,
            'expandedBytes': total, 'files': len(files), 'checksumPath': str(checksum_path)}


def register_release(directory: Path, package: dict, index_path: Path) -> dict:
    """Record a real local artifact; hosted URLs are added only after publication."""
    manifest = check_manifest(directory)
    root = index_path.resolve().parent
    archive = Path(package['path']).resolve()
    checksum = Path(package['checksumPath']).resolve()
    if not archive.is_relative_to(root) or not checksum.is_relative_to(root):
        raise ValueError('Registered artifacts must be inside the release index directory')
    if sha256(archive) != package['sha256']:
        raise ValueError('Packaged archive differs from its recorded SHA-256')
    provenance = manifest['provenance']
    entry = {
        'datasetVersion': manifest['datasetVersion'], 'runId': provenance['runId'],
        'scope': manifest['scope'], 'resultsSha256': provenance['resultsSha256'],
        'panelSha256': provenance['panelSha256'],
        'analysisRevision': provenance['code']['gitRevision'],
        'exportRevision': provenance['exportCode']['gitRevision'],
        'archive': {'path': archive.relative_to(root).as_posix(),
                    'checksumPath': checksum.relative_to(root).as_posix(),
                    **{key: package[key] for key in ('sha256', 'bytes', 'expandedBytes', 'files')}},
    }
    index = json.loads(index_path.read_text()) if index_path.exists() else {'schemaVersion': '1.0', 'releases': []}
    if index.get('schemaVersion') != '1.0' or not isinstance(index.get('releases'), list):
        raise ValueError('Unsupported release index')
    existing = next((release for release in index['releases']
                     if release['datasetVersion'] == entry['datasetVersion']), None)
    if existing is not None and existing != entry:
        raise ValueError('A dataset version is already registered with different artifact metadata')
    if existing is None:
        index['releases'].append(entry)
    index['status'] = 'Complete artifacts are packaged locally. No public download URL is registered.'
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n')
    return entry


def restore_archive(archive_path: Path, output: Path, expected_hash: str) -> dict:
    if output.exists():
        raise FileExistsError(f'Refusing to replace {output}')
    if len(expected_hash) != 64 or any(c not in '0123456789abcdef' for c in expected_hash.lower()):
        raise ValueError('Expected SHA-256 must contain 64 hexadecimal characters')
    if sha256(archive_path) != expected_hash.lower():
        raise ValueError('Archive SHA-256 does not match the pinned release')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=output.parent) as temp:
        staged = Path(temp) / 'data'
        staged.mkdir()
        with tarfile.open(archive_path, mode='r:gz') as archive:
            total = 0
            names = set()
            for member in archive:
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or '..' in relative.parts or '\\' in member.name:
                    raise ValueError('Archive member escapes the release directory')
                if not relative.parts or relative.as_posix() in names:
                    raise ValueError('Empty or duplicate archive member')
                names.add(relative.as_posix())
                if member.isdir():
                    (staged / relative).mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise ValueError('Only regular files and directories are accepted')
                total += member.size
                if total > MAX_EXPANDED_BYTES:
                    raise ValueError('Expanded release exceeds the size budget')
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError('Unable to read archive member')
                with source, destination.open('xb') as target:
                    shutil.copyfileobj(source, target)
        manifest = check_manifest(staged)
        staged.rename(output)
    return {'datasetVersion': manifest['datasetVersion'], 'output': str(output), 'sha256': expected_hash}


def fetch_release(url: str, output: Path, expected_hash: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError('Dataset downloads require an HTTPS URL without embedded credentials')
    if output.exists():
        raise FileExistsError(f'Refusing to replace {output}')
    with tempfile.TemporaryDirectory(prefix='elections-download-') as temp:
        archive = Path(temp) / 'release.tar.gz'
        with urlopen(url, timeout=60) as response, archive.open('wb') as target:
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise ValueError('Downloaded release exceeds the size budget')
                target.write(block)
        return restore_archive(archive, output, expected_hash)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    pack = commands.add_parser('pack')
    pack.add_argument('--directory', type=Path, required=True)
    pack.add_argument('--output', type=Path, required=True)
    pack.add_argument('--index', type=Path, help='Register the real artifact in this release index')
    restore = commands.add_parser('restore')
    restore.add_argument('--archive', type=Path, required=True)
    restore.add_argument('--sha256', required=True)
    restore.add_argument('--output', type=Path, required=True)
    fetch = commands.add_parser('fetch')
    fetch.add_argument('--url', required=True)
    fetch.add_argument('--sha256', required=True)
    fetch.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'pack':
        result = pack_release(args.directory, args.output)
        if args.index:
            result['release'] = register_release(args.directory, result, args.index)
    elif args.command == 'restore':
        result = restore_archive(args.archive, args.output, args.sha256)
    else:
        result = fetch_release(args.url, args.output, args.sha256)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
