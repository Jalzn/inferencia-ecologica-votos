import type { FeatureCollection, Geometry } from 'geojson';

export const schemaVersion = '2.0';
export const destinationIds = ['lula', 'flavio', 'blank', 'null', 'abstention'] as const;
export type DestinationId = (typeof destinationIds)[number];
export type CountRange = { min: number; max: number };
export type FinalistRanges = { lula: CountRange; flavio: CountRange };
export type FlowRow = {
  originId: string;
  observed: number;
  estimated: Record<DestinationId, number>;
  sensitivity: FinalistRanges | null;
  identificationBounds: FinalistRanges;
};
export type PlaceKind = 'national' | 'state' | 'municipality' | 'foreign';
export type SearchPlace = {
  id: string;
  name: string;
  stateCode: string;
  kind: PlaceKind;
  parentId: string | null;
  ibgeCode?: string;
  /** Former or TSE names that differ from the official IBGE name. */
  aliases?: string[];
};
export type Place = SearchPlace & {
  electorate: number;
  sectionCount: number;
  rows: FlowRow[];
};
export type Resource = { path: string; bytes: number; sha256: string; encoding: 'json' | 'gzip' };
export type DisplayGroup = { id: string; label: string; shortLabel: string; members: string[] };
export type Origin = { id: string; label: string; shortLabel: string; kind: string };
export type ModelDescription = {
  id: string;
  label: string;
  status: string;
  scenarioCount: number;
  scenarios: { id: string; label: string }[];
  /** Reader-facing Portuguese text produced with the analysis run. */
  sensitivityDescription: string;
  /** Reader-facing Portuguese text stating the assumptions of the identification bounds. */
  boundsDescription: string;
};
export type Manifest = {
  schemaVersion: typeof schemaVersion;
  datasetVersion: string;
  electionYear: number;
  scope: 'full' | 'fixture';
  model: ModelDescription;
  origins: Origin[];
  displayGroups: DisplayGroup[];
  destinations: unknown[];
  resources: {
    national: Resource;
    search: Resource;
    states: Record<string, Resource>;
  };
  provenance: Record<string, unknown>;
};
export type LayerId = 'states' | 'municipalities';
export type Layer = { id: LayerId; label: string; kind: 'polygon' };
export type MapProperties = {
  id: string;
  name?: string;
  [key: string]: unknown;
};
export type AreaBundle = {
  schemaVersion: typeof schemaVersion;
  datasetVersion: string;
  id: string;
  level: 'national' | 'state';
  place: Place;
  children: Place[];
  geometry: Record<string, FeatureCollection<Geometry, MapProperties>>;
  layers: Layer[];
  defaultLayer: LayerId;
  sourceLabel?: string;
  limitations?: string[];
};
export type SearchIndex = {
  schemaVersion: typeof schemaVersion;
  datasetVersion: string;
  places: SearchPlace[];
};
export type Selection = { place: string; origin: string };
