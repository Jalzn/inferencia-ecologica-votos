import { afterEach, describe, expect, it, vi } from 'vitest';
import { gzipSync } from 'node:zlib';
import { DatasetClient, validateManifest } from '../src/data/client';
import { bundleIdForPlace, canonicalPlaceId } from '../src/data/places';
import type { Manifest, Resource } from '../src/data/types';

async function descriptor(bytes: Uint8Array, encoding: Resource['encoding']): Promise<Resource> {
  const hash = await crypto.subtle.digest('SHA-256', new Uint8Array(bytes));
  return {
    path: encoding === 'gzip' ? 'states/MG.json.bin' : 'national.json',
    bytes: bytes.length,
    sha256: Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join(''),
    encoding,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('Verified resource loading', () => {
  it('verifies gzip bytes, decodes explicitly, and reuses the cached object', async () => {
    const payload = { name: 'São João', count: 12 };
    const bytes = gzipSync(JSON.stringify(payload));
    const resource = await descriptor(bytes, 'gzip');
    const fetch = vi.fn(async (_url: URL) => new Response(new Uint8Array(bytes)));
    vi.stubGlobal('fetch', fetch);
    const client = new DatasetClient(new URL('https://example.test/project/data/'));
    const first = await client.resource(resource);
    expect(first).toEqual(payload);
    expect(await client.resource(resource)).toBe(first);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(fetch.mock.calls[0][0])).toBe(
      'https://example.test/project/data/states/MG.json.bin',
    );
    const aborted = new AbortController();
    aborted.abort();
    await expect(client.resource(resource, aborted.signal)).rejects.toMatchObject({
      name: 'AbortError',
    });
  });

  it('rejects same-length corruption and truncated responses before parsing JSON', async () => {
    const bytes = new TextEncoder().encode('{"count":12}');
    const resource = await descriptor(bytes, 'json');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"count":99}')),
    );
    const client = new DatasetClient(new URL('https://example.test/data/'));
    await expect(client.resource(resource)).rejects.toThrow('integridade');
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response('{"count":1}')),
    );
    await expect(client.resource(resource)).rejects.toThrow('incompleto');
  });
});

const resource = (path: string): Resource => ({
  path,
  bytes: 10,
  sha256: 'a'.repeat(64),
  encoding: path.endsWith('.bin') ? 'gzip' : 'json',
});
function manifest(): Manifest {
  return {
    schemaVersion: '2.0',
    datasetVersion: 'v1',
    electionYear: 2026,
    scope: 'fixture',
    model: {
      id: 'm',
      label: 'Modelo',
      status: 'Estimativas condicionais.',
      scenarioCount: 2,
      scenarios: [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
      ],
      sensitivityDescription: 'A faixa varia o agrupamento.',
      boundsDescription: 'Limites contábeis.',
    },
    origins: [{ id: 'blank', label: 'Brancos', shortLabel: 'B', kind: 'blank' }],
    displayGroups: [{ id: 'blank', label: 'Brancos', shortLabel: 'B', members: ['blank'] }],
    destinations: [],
    resources: {
      national: resource('national.json'),
      search: resource('search-index.json'),
      states: { MG: resource('states/MG.json.bin'), ZZ: resource('states/ZZ.json.bin') },
    },
    provenance: {},
  };
}

describe('Release catalog 2.0', () => {
  it('accepts a 2.0 manifest and rejects 1.0 or missing model descriptions', () => {
    expect(validateManifest(manifest()).model.sensitivityDescription).toContain('agrupamento');
    expect(() => validateManifest({ ...manifest(), schemaVersion: '1.0' })).toThrow('compatível');
    const withoutBounds = manifest();
    withoutBounds.model.boundsDescription = ' ';
    expect(() => validateManifest(withoutBounds)).toThrow('modelo');
    const withoutScenarios = manifest();
    withoutScenarios.model.scenarios = [];
    expect(() => validateManifest(withoutScenarios)).toThrow('modelo');
  });

  it('resolves municipalities and foreign localities to their state bundle', () => {
    const release = manifest();
    const client = new DatasetClient(new URL('https://example.test/data/'));
    expect(client.descriptor(release, 'BR')).toBe(release.resources.national);
    expect(client.descriptor(release, 'MG')).toBe(release.resources.states.MG);
    expect(client.descriptor(release, 'MG:41238')).toBe(release.resources.states.MG);
    expect(client.descriptor(release, 'ZZ')).toBe(release.resources.states.ZZ);
    expect(client.descriptor(release, 'ZZ:29254')).toBe(release.resources.states.ZZ);
    expect(client.descriptor(release, 'SP:71072')).toBeUndefined();
    expect(client.descriptor(release, 'MG:41238:r:18')).toBeUndefined();
    expect(client.descriptor(release, 'constructor')).toBeUndefined();
    expect(client.available(release, 'MG:41238')).toBe(true);
    expect(client.available(release, 'SP')).toBe(false);
  });

  it('resolves link places to their bundles', () => {
    expect(canonicalPlaceId(' MG:41238 ')).toBe('MG:41238');
    expect(canonicalPlaceId('')).toBe('BR');
    expect(canonicalPlaceId(null)).toBe('BR');
    expect(bundleIdForPlace('BR')).toBe('BR');
    expect(bundleIdForPlace('ZZ:29254')).toBe('ZZ');
    expect(bundleIdForPlace('mg:1')).toBeNull();
    expect(bundleIdForPlace('MG:41238:r:18')).toBeNull();
  });
});

describe('State bundle loading', () => {
  function stateBundle(id: string) {
    const rows = [
      {
        originId: 'blank',
        observed: 10,
        estimated: { lula: 4, flavio: 3, blank: 3, null: 0, abstention: 0 },
        sensitivity: null,
        identificationBounds: { lula: { min: 0, max: 10 }, flavio: { min: 0, max: 10 } },
      },
    ];
    const place = (placeId: string, kind: string, parentId: string) => ({
      id: placeId,
      name: placeId,
      stateCode: id,
      kind,
      parentId,
      electorate: 10,
      sectionCount: 1,
      rows,
    });
    return {
      schemaVersion: '2.0',
      datasetVersion: 'v1',
      id,
      level: 'state',
      place: place(id, 'state', 'BR'),
      children: [place(`${id}:41238`, 'municipality', id)],
      geometry: { municipalities: { type: 'FeatureCollection', features: [] } },
      layers: [{ id: 'municipalities', label: 'Municípios', kind: 'polygon' }],
      defaultLayer: 'municipalities',
    };
  }

  it('loads a municipality through its state bundle and rejects a mismatched package', async () => {
    const bytes = gzipSync(JSON.stringify(stateBundle('MG')));
    const release = manifest();
    release.resources.states.MG = { ...(await descriptor(bytes, 'gzip')) };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(new Uint8Array(bytes))),
    );
    const client = new DatasetClient(new URL('https://example.test/data/'));
    const loaded = await client.bundle(release, 'MG:41238');
    expect(loaded.id).toBe('MG');
    expect(loaded.children.map((place) => place.id)).toEqual(['MG:41238']);

    const other = gzipSync(JSON.stringify(stateBundle('SP')));
    release.resources.states.MG = {
      ...(await descriptor(other, 'gzip')),
      path: 'states/x.json.bin',
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(new Uint8Array(other))),
    );
    await expect(client.bundle(release, 'MG:41238')).rejects.toThrow('não corresponde');
    await expect(client.bundle(release, 'SP:1')).rejects.toThrow('Minas Gerais');
  });
});
