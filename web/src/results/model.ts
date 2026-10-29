import { canonicalPlaceId } from '../data/places';
import {
  destinationIds,
  type DestinationId,
  type DisplayGroup,
  type FinalistRanges,
  type FlowRow,
  type Place,
  type SearchPlace,
  type Selection,
} from '../data/types';

const number = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat('pt-BR', { notation: 'compact', maximumFractionDigits: 1 });

/** Observed origin bases below this count mostly reproduce the regional model pattern. */
export const smallBaseLimit = 100;

/**
 * A display group's presentation row. Point counts and observed bases are summed; sensitivity and
 * identification bounds exist only for single-member groups, never as sums of member endpoints.
 */
export type SummaryRow = {
  groupId: string;
  observed: number;
  estimated: Record<DestinationId, number>;
  sensitivity: FinalistRanges | null;
  identificationBounds: FinalistRanges | null;
};

export function summarize(place: Place, group: DisplayGroup): SummaryRow {
  const rows = group.members.map((id) => place.rows.find((row) => row.originId === id));
  if (rows.some((row) => !row)) throw new Error(`Missing origin in ${place.id}`);
  const present = rows as FlowRow[];
  const single = present.length === 1 ? present[0] : null;
  return {
    groupId: group.id,
    observed: present.reduce((sum, row) => sum + row.observed, 0),
    estimated: Object.fromEntries(
      destinationIds.map((id) => [id, present.reduce((sum, row) => sum + row.estimated[id], 0)]),
    ) as SummaryRow['estimated'],
    sensitivity: single?.sensitivity ?? null,
    identificationBounds: single?.identificationBounds ?? null,
  };
}

export function share(count: number, observed: number): number | null {
  return observed > 0 ? count / observed : null;
}
export function hasAssociatedSections(place: Place): boolean {
  return place.sectionCount > 0;
}
/** A present origin (or display group) whose observed base is under {@link smallBaseLimit}. */
export function isSmallBase(observed: number): boolean {
  return observed > 0 && observed < smallBaseLimit;
}
export function balance(row: Pick<SummaryRow, 'observed' | 'estimated'>): number | null {
  return share(row.estimated.lula - row.estimated.flavio, row.observed);
}

// Floating-point noise must not turn an exact 1% or 99% into "<1%" or ">99%".
const percentEpsilon = 1e-9;

/** Integer percentages: the estimates do not support finer precision. */
export function formatPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '—';
  const percent = value * 100;
  if (percent > 0 && percent < 1 - percentEpsilon) return '<1%';
  if (percent > 99 + percentEpsilon && percent < 100 - percentEpsilon) return '>99%';
  return `${number.format(Math.round(percent))}%`;
}
/** Percentage-point difference with the same integer precision as shares. */
export function formatPoints(value: number): string {
  return formatPercent(Math.abs(value)).replace('%', ' p.p.');
}
export function formatCount(value: number, estimated = false): string {
  if (estimated && value > 0 && value < 1) return '<1';
  return `${estimated && value !== 0 ? '≈' : ''}${number.format(value)}`;
}
/** Estimated counts never show decimal votes; large counts use compact notation. */
export function formatCompact(value: number): string {
  if (value > 0 && value < 1) return '<1';
  return `≈${value < 1000 ? number.format(Math.round(value)) : compact.format(value)}`;
}
export function initials(label: string): string {
  const words = label.trim().split(/\s+/);
  return words.length > 1 ? words[0][0] + words[words.length - 1][0] : words[0].slice(0, 2);
}
export function normalize(value: string): string {
  return value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}
export function searchPlaces(places: SearchPlace[], query: string): SearchPlace[] {
  const normalized = normalize(query);
  if (!normalized) return [];
  return places
    .map((place) => {
      const name = normalize(place.name);
      const aliases = (place.aliases || []).map(normalize);
      const fields = normalize(
        [
          place.name,
          place.stateCode,
          place.id,
          place.ibgeCode || '',
          ...(place.aliases || []),
        ].join(' '),
      );
      const score =
        name === normalized || aliases.includes(normalized)
          ? 0
          : name.startsWith(normalized) || aliases.some((alias) => alias.startsWith(normalized))
            ? 1
            : name.includes(normalized)
              ? 2
              : fields.includes(normalized)
                ? 3
                : 9;
      return { place, score };
    })
    .filter((item) => item.score < 9)
    .sort((a, b) => a.score - b.score || a.place.name.localeCompare(b.place.name, 'pt-BR'))
    .slice(0, 10)
    .map((item) => item.place);
}
/** Reads a shared link; the explorer replaces an unknown origin with the first display group. */
export function readSelection(search = window.location.search): Selection {
  const params = new URLSearchParams(search);
  return {
    place: canonicalPlaceId(params.get('place')),
    origin: params.get('origin') || 'augusto_cury',
  };
}
export function selectionQuery(selection: Selection): string {
  return `?${new URLSearchParams({ place: selection.place, origin: selection.origin })}`;
}
export function placeKindLabel(place: Pick<SearchPlace, 'id' | 'kind'>): string {
  if (place.id === 'ZZ') return 'Eleitores no exterior';
  return {
    national: 'Brasil · inclui exterior',
    state: 'Estado',
    municipality: 'Município',
    foreign: 'Localidade no exterior',
  }[place.kind];
}
