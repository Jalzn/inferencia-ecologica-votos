"""Pinned external inputs: download, local mirrors, and integrity verification."""
from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
REGISTRY_PATH = REPOSITORY_ROOT / "data/sources.json"
DEFAULT_RAW_ROOT = REPOSITORY_ROOT / "data/raw/2026"


@dataclass(frozen=True)
class SourceFile:
    id: str
    path: str
    url: str
    bytes: int
    sha256: str
    retrieved: str
    publisher: str
    description: str
    decode_gzip: bool = False


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, SourceFile]:
    data = json.loads(path.read_text())
    sources = {}
    for entry in data["files"]:
        source = SourceFile(entry["id"], entry["path"], entry["url"], entry["bytes"], entry["sha256"],
                            entry["retrieved"], entry["publisher"], entry["description"],
                            entry.get("decodeGzip", False))
        if source.id in sources or ".." in Path(source.path).parts or Path(source.path).is_absolute():
            raise ValueError(f"Invalid source registry entry: {source.id}")
        sources[source.id] = source
    return sources


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_path(raw_root: Path, source_id: str, registry: dict[str, SourceFile] | None = None) -> Path:
    source = (registry or load_registry())[source_id]
    return raw_root / source.path


def _matches(path: Path, source: SourceFile) -> bool:
    return path.is_file() and path.stat().st_size == source.bytes and file_sha256(path) == source.sha256


def verify_sources(raw_root: Path = DEFAULT_RAW_ROOT, registry: dict[str, SourceFile] | None = None) -> dict[str, str]:
    """Require every registered file to exist with its pinned size and digest."""
    registry = registry or load_registry()
    for source in registry.values():
        path = raw_root / source.path
        if not _matches(path, source):
            raise ValueError(f"Source {source.id} is missing or differs from its pinned digest: {path}")
    return {source.id: source.sha256 for source in registry.values()}


def _find_in_mirrors(source: SourceFile, mirrors: list[Path]) -> Path | None:
    for mirror in mirrors:
        for candidate in sorted(mirror.iterdir()) if mirror.is_dir() else []:
            if candidate.is_file() and candidate.stat().st_size == source.bytes and _matches(candidate, source):
                return candidate
    return None


def _download(source: SourceFile, target: Path) -> None:
    request = urllib.request.Request(source.url, headers={"User-Agent": "elections-pipeline"})
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        partial = Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                shutil.copyfileobj(response, temporary)
            temporary.close()
            content_head = partial.read_bytes()[:2]
            if source.decode_gzip and content_head == b"\x1f\x8b":
                partial.write_bytes(gzip.decompress(partial.read_bytes()))
            if not _matches(partial, source):
                raise ValueError(f"Downloaded {source.id} differs from its pinned digest; the publisher may have changed it")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)


def fetch_sources(raw_root: Path = DEFAULT_RAW_ROOT, mirrors: list[Path] | None = None,
                  registry: dict[str, SourceFile] | None = None) -> dict[str, str]:
    """Place each pinned file under raw_root from a matching mirror or its URL.

    Mirrors are matched by size and SHA-256, never by name, so a local copy can
    only stand in for the exact registered bytes.
    """
    registry = registry or load_registry()
    actions = {}
    for source in registry.values():
        target = raw_root / source.path
        target.parent.mkdir(parents=True, exist_ok=True)
        if _matches(target, source):
            actions[source.id] = "present"
            continue
        local = _find_in_mirrors(source, mirrors or [])
        if local is not None:
            shutil.copyfile(local, target)
            actions[source.id] = f"copied from {local}"
        else:
            _download(source, target)
            actions[source.id] = f"downloaded from {source.url}"
    verify_sources(raw_root, registry)
    return actions
