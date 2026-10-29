import { bundleIdForPlace, nationalId } from './places';
import {
  destinationIds,
  schemaVersion,
  type AreaBundle,
  type FinalistRanges,
  type Manifest,
  type Place,
  type Resource,
  type SearchIndex,
} from './types';

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

export function safeResourcePath(path: string): string {
  if (
    typeof path !== 'string' ||
    !/^[a-zA-Z0-9_./-]+$/.test(path) ||
    path.startsWith('/') ||
    path.split('/').some((part) => part === '..' || part === '.' || part === '')
  ) {
    throw new Error('Caminho de dados inválido.');
  }
  return path;
}

function text(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

export function validateManifest(value: unknown): Manifest {
  if (
    !object(value) ||
    value.schemaVersion !== schemaVersion ||
    !['full', 'fixture'].includes(String(value.scope)) ||
    typeof value.datasetVersion !== 'string' ||
    !object(value.resources) ||
    !object(value.resources.states) ||
    !Array.isArray(value.displayGroups) ||
    !Array.isArray(value.origins) ||
    !object(value.model)
  )
    throw new Error('Esta versão dos dados não é compatível com a página.');
  const model = value.model;
  if (
    !text(model.label) ||
    !text(model.status) ||
    !Number.isSafeInteger(model.scenarioCount) ||
    !Array.isArray(model.scenarios) ||
    !model.scenarios.length ||
    !text(model.sensitivityDescription) ||
    !text(model.boundsDescription)
  )
    throw new Error('A descrição do modelo está incompleta.');
  const manifest = value as Manifest;
  const resources = [
    manifest.resources.national,
    manifest.resources.search,
    ...Object.values(manifest.resources.states),
  ];
  for (const resource of resources) {
    if (
      !resource ||
      !Number.isSafeInteger(resource.bytes) ||
      resource.bytes < 0 ||
      !/^[a-f0-9]{64}$/.test(resource.sha256) ||
      !['json', 'gzip'].includes(resource.encoding)
    )
      throw new Error('O catálogo de dados está incompleto.');
    safeResourcePath(resource.path);
  }
  const origins = new Set(manifest.origins.map((origin) => origin.id));
  if (
    origins.size !== manifest.origins.length ||
    manifest.displayGroups.some(
      (group) => !group.members.length || group.members.some((id) => !origins.has(id)),
    )
  ) {
    throw new Error('As categorias de origem são inconsistentes.');
  }
  return manifest;
}

const countTolerance = 0.0011;

function validRanges(value: unknown): value is FinalistRanges {
  return (
    object(value) &&
    (['lula', 'flavio'] as const).every((id) => {
      const range = value[id];
      return (
        object(range) &&
        Number.isFinite(range.min) &&
        Number.isFinite(range.max) &&
        (range.min as number) >= 0 &&
        (range.min as number) <= (range.max as number) + countTolerance
      );
    })
  );
}

const childKinds: Record<AreaBundle['level'], Place['kind'][]> = {
  national: ['state'],
  state: ['municipality', 'foreign'],
};

export function validateBundle(value: unknown, version: string, origins?: string[]): AreaBundle {
  if (
    !object(value) ||
    value.schemaVersion !== schemaVersion ||
    value.datasetVersion !== version ||
    !['national', 'state'].includes(String(value.level)) ||
    typeof value.id !== 'string' ||
    !object(value.place) ||
    !Array.isArray(value.children) ||
    !Array.isArray(value.layers) ||
    !object(value.geometry)
  ) {
    throw new Error('O pacote geográfico pertence a outra versão ou está incompleto.');
  }
  const bundle = value as AreaBundle;
  for (const place of [bundle.place, ...bundle.children]) {
    if (
      typeof place.id !== 'string' ||
      typeof place.name !== 'string' ||
      !Array.isArray(place.rows) ||
      !Number.isFinite(place.sectionCount)
    )
      throw new Error('Local inválido no pacote.');
    if (
      place !== bundle.place &&
      (!childKinds[bundle.level].includes(place.kind) ||
        (bundle.level === 'state' && bundleIdForPlace(place.id) !== bundle.id))
    )
      throw new Error('Local inválido no pacote.');
    const rowIds = new Set(place.rows.map((row) => row.originId));
    if (
      rowIds.size !== place.rows.length ||
      (origins && (rowIds.size !== origins.length || origins.some((id) => !rowIds.has(id))))
    ) {
      throw new Error('As categorias deste lugar estão incompletas ou repetidas.');
    }
    for (const row of place.rows) {
      if (
        !Number.isFinite(row.observed) ||
        row.observed < 0 ||
        !destinationIds.every(
          (id) => Number.isFinite(row.estimated?.[id]) && row.estimated[id] >= 0,
        )
      ) {
        throw new Error('Contagem inválida nos dados.');
      }
      const total = destinationIds.reduce((sum, id) => sum + row.estimated[id], 0);
      if (Math.abs(total - row.observed) > countTolerance)
        throw new Error('Os destinos não recompõem o total de origem.');
      if (
        !validRanges(row.identificationBounds) ||
        (row.sensitivity !== null && !validRanges(row.sensitivity))
      )
        throw new Error('Faixa inválida nos dados.');
    }
  }
  return bundle;
}

export class DatasetClient {
  readonly base: URL;
  private cache = new Map<string, { value: unknown; size: number }>();
  private cacheSize = 0;
  private readonly cacheLimit = 64 * 1024 * 1024;

  constructor(base: URL) {
    this.base = base;
  }

  async manifest(signal?: AbortSignal): Promise<Manifest> {
    const response = await fetch(new URL('manifest.json', this.base), { signal });
    if (!response.ok) throw new Error('Não foi possível abrir o catálogo de dados.');
    return validateManifest(await response.json());
  }

  async resource<T>(resource: Resource, signal?: AbortSignal): Promise<T> {
    signal?.throwIfAborted();
    const key = `${resource.path}:${resource.sha256}`;
    const cached = this.cache.get(key);
    if (cached) {
      this.cache.delete(key);
      this.cache.set(key, cached);
      return cached.value as T;
    }
    const response = await fetch(new URL(safeResourcePath(resource.path), this.base), { signal });
    if (!response.ok) throw new Error(`Não foi possível carregar este lugar (${response.status}).`);
    const bytes = await response.arrayBuffer();
    if (bytes.byteLength !== resource.bytes)
      throw new Error('O arquivo recebido está incompleto. Tente novamente.');
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('');
    if (hash !== resource.sha256)
      throw new Error('A integridade dos dados não pôde ser confirmada.');
    signal?.throwIfAborted();
    const text =
      resource.encoding === 'gzip'
        ? await new Response(
            new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')),
          ).text()
        : new TextDecoder().decode(bytes);
    const value = JSON.parse(text) as T;
    signal?.throwIfAborted();
    // Account for the decoded text, rather than the much smaller gzip payload.
    const size = text.length * 2;
    if (size <= this.cacheLimit) {
      while (this.cacheSize + size > this.cacheLimit && this.cache.size) {
        const oldest = this.cache.keys().next().value!;
        this.cacheSize -= this.cache.get(oldest)!.size;
        this.cache.delete(oldest);
      }
      if (this.cache.has(key)) this.cacheSize -= this.cache.get(key)!.size;
      this.cache.set(key, { value, size });
      this.cacheSize += size;
    }
    return value;
  }

  descriptor(manifest: Manifest, placeId: string): Resource | undefined {
    const bundleId = bundleIdForPlace(placeId);
    if (!bundleId) return undefined;
    return bundleId === nationalId
      ? manifest.resources.national
      : Object.hasOwn(manifest.resources.states, bundleId)
        ? manifest.resources.states[bundleId]
        : undefined;
  }

  available(manifest: Manifest, placeId: string): boolean {
    return !!this.descriptor(manifest, placeId);
  }

  /** Loads the national or state bundle that contains `placeId`. */
  async bundle(manifest: Manifest, placeId: string, signal?: AbortSignal): Promise<AreaBundle> {
    const descriptor = this.descriptor(manifest, placeId);
    if (!descriptor)
      throw new Error(
        manifest.scope === 'fixture' && bundleIdForPlace(placeId)
          ? 'Este lugar está disponível na base completa. A amostra local inclui Minas Gerais.'
          : 'Este lugar não foi encontrado nesta versão dos dados.',
      );
    const bundle = validateBundle(
      await this.resource(descriptor, signal),
      manifest.datasetVersion,
      manifest.origins.map((origin) => origin.id),
    );
    if (bundle.id !== bundleIdForPlace(placeId))
      throw new Error('O pacote geográfico não corresponde ao lugar pedido.');
    return bundle;
  }

  async search(manifest: Manifest, signal?: AbortSignal): Promise<SearchIndex> {
    const value = await this.resource<SearchIndex>(manifest.resources.search, signal);
    if (
      value.schemaVersion !== schemaVersion ||
      value.datasetVersion !== manifest.datasetVersion ||
      !Array.isArray(value.places)
    )
      throw new Error('Índice de busca incompatível.');
    return value;
  }
}
