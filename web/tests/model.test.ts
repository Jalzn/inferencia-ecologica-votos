import { describe, expect, it } from 'vitest';
import type { DisplayGroup, FlowRow, Place } from '../src/data/types';
import {
  balance,
  formatCompact,
  formatPercent,
  formatPoints,
  isSmallBase,
  placeKindLabel,
  readSelection,
  searchPlaces,
  selectionQuery,
  share,
  summarize,
} from '../src/results/model';
import { safeResourcePath, validateBundle } from '../src/data/client';

const group: DisplayGroup = {
  id: 'null',
  label: 'Nulos',
  shortLabel: 'N',
  members: ['null_ballot', 'null_technical'],
};
function row(originId: string, observed: number, lula: number, flavio: number): FlowRow {
  return {
    originId,
    observed,
    estimated: { lula, flavio, blank: observed - lula - flavio, null: 0, abstention: 0 },
    sensitivity: { lula: { min: lula / 2, max: lula }, flavio: { min: 0, max: flavio } },
    identificationBounds: {
      lula: { min: 0, max: observed },
      flavio: { min: 0, max: observed },
    },
  };
}
function place(rows: FlowRow[], id = 'MG:1'): Place {
  return {
    id,
    name: 'São João',
    kind: 'municipality',
    stateCode: 'MG',
    parentId: 'MG',
    electorate: 120,
    sectionCount: 1,
    rows,
  };
}
function bundle(rows: FlowRow[], children: Place[] = []) {
  return {
    schemaVersion: '2.0',
    datasetVersion: 'v1',
    id: 'MG',
    level: 'state',
    place: { ...place(rows, 'MG'), kind: 'state', parentId: 'BR' },
    children,
    layers: [{ id: 'municipalities', label: 'Municípios', kind: 'polygon' }],
    defaultLayer: 'municipalities',
    geometry: {},
  };
}

describe('Presentation preserves statistical meaning', () => {
  it('uses the whole origin for the red-blue balance', () => {
    const result = summarize(
      place([row('null_ballot', 100, 30, 10), row('null_technical', 20, 5, 10)]),
      group,
    );
    expect(result.observed).toBe(120);
    expect(result.estimated.blank).toBe(65);
    expect(balance(result)).toBeCloseTo(15 / 120);
  });
  it('never sums sensitivity or bounds endpoints across the members of a group', () => {
    const result = summarize(
      place([row('null_ballot', 100, 30, 10), row('null_technical', 20, 5, 10)]),
      group,
    );
    expect(result.sensitivity).toBeNull();
    expect(result.identificationBounds).toBeNull();
  });
  it('preserves ranges and bounds for a single origin and rejects missing rows', () => {
    const single = { ...group, members: ['null_ballot'] };
    const source = row('null_ballot', 100, 30, 10);
    const result = summarize(place([source]), single);
    expect(result.sensitivity).toEqual(source.sensitivity);
    expect(result.identificationBounds).toEqual(source.identificationBounds);
    expect(() => summarize(place([source]), group)).toThrow('Missing origin');
  });
  it('formats shares as integer percentages with explicit extremes', () => {
    expect(share(0, 0)).toBeNull();
    expect(formatPercent(share(0, 0))).toBe('—');
    expect(formatPercent(0)).toBe('0%');
    expect(formatPercent(0.00003)).toBe('<1%');
    expect(formatPercent(0.0099)).toBe('<1%');
    expect(formatPercent(0.01)).toBe('1%');
    expect(formatPercent(0.4849)).toBe('48%');
    expect(formatPercent(0.4851)).toBe('49%');
    expect(formatPercent(0.99)).toBe('99%');
    expect(formatPercent(0.9901)).toBe('>99%');
    expect(formatPercent(0.99999)).toBe('>99%');
    expect(formatPercent(1)).toBe('100%');
    expect(formatPercent(57 / 57)).toBe('100%');
    expect(formatPoints(-0.123)).toBe('12 p.p.');
    expect(formatPoints(0.004)).toBe('<1 p.p.');
  });
  it('marks only present origins below 100 observed voters as small bases', () => {
    expect(isSmallBase(0)).toBe(false);
    expect(isSmallBase(1)).toBe(true);
    expect(isSmallBase(99)).toBe(true);
    expect(isSmallBase(100)).toBe(false);
  });
  it('searches accents and geography codes without changing inputs', () => {
    const places = [place([]), { ...place([], 'MG:2'), name: 'Betim', ibgeCode: '3106705' }];
    expect(searchPlaces(places, 'sao joao')[0].id).toBe('MG:1');
    expect(searchPlaces(places, '3106705')[0].id).toBe('MG:2');
    expect(places).toHaveLength(2);
  });
  it('finds municipalities by their TSE name when it differs from the IBGE name', () => {
    const places = [{ ...place([], 'RN:17035'), name: 'Januário Cicco', aliases: ['Boa Saúde'] }];
    expect(searchPlaces(places, 'boa saude')[0].id).toBe('RN:17035');
    expect(searchPlaces(places, 'boa sa')[0].id).toBe('RN:17035');
  });
  it('shows estimated counts without decimal votes', () => {
    expect(formatCompact(16.4)).toBe('≈16');
    expect(formatCompact(999.6)).toBe('≈1.000');
    expect(formatCompact(0.4)).toBe('<1');
    expect(formatCompact(0)).toBe('≈0');
    expect(formatCompact(1_701_819)).toMatch(/^≈1,7\s?mi/);
  });
  it('labels place kinds, including voters abroad', () => {
    expect(placeKindLabel({ id: 'ZZ', kind: 'state' })).toBe('Eleitores no exterior');
    expect(placeKindLabel({ id: 'MG', kind: 'state' })).toBe('Estado');
    expect(placeKindLabel({ id: 'ZZ:29254', kind: 'foreign' })).toBe('Localidade no exterior');
  });
});

describe('Shared links', () => {
  it('round-trips municipality selections', () => {
    const state = { place: 'MG:41238', origin: 'blank' };
    expect(selectionQuery(state)).toBe('?place=MG%3A41238&origin=blank');
    expect(readSelection(selectionQuery(state))).toEqual(state);
  });
  it('defaults to Brazil and the first eliminated candidate', () => {
    expect(readSelection('')).toEqual({ place: 'BR', origin: 'augusto_cury' });
    expect(readSelection('?place=%20MG%20&origin=blank')).toEqual({ place: 'MG', origin: 'blank' });
  });
});

describe('Data boundary', () => {
  it('rejects remote URLs, traversal, encoded paths, and injected queries', () => {
    for (const path of [
      '../outside.json',
      '/data.json',
      'https://evil.test/a',
      'states/%2e%2e/a',
      'states/a.json?x=1',
      'states//a',
    ])
      expect(() => safeResourcePath(path)).toThrow();
    expect(safeResourcePath('states/MG.json.bin')).toBe('states/MG.json.bin');
  });
  it('accepts a 2.0 state bundle and rejects cross-release, 1.0 and nonconserving data', () => {
    const valid = bundle([row('blank', 100, 30, 20)], [place([row('blank', 10, 3, 2)])]);
    expect(validateBundle(valid, 'v1').children[0].id).toBe('MG:1');
    expect(() => validateBundle(valid, 'v2')).toThrow();
    expect(() => validateBundle({ ...valid, schemaVersion: '1.0' }, 'v1')).toThrow();
    expect(() => validateBundle({ ...valid, level: 'municipality' }, 'v1')).toThrow();
    valid.place.rows[0].estimated.lula += 10;
    expect(() => validateBundle(valid, 'v1')).toThrow('recompõem');
  });
  it('requires identification bounds on every row and valid sensitivity when present', () => {
    const source = row('blank', 100, 30, 20);
    const { identificationBounds: _omitted, ...withoutBounds } = source;
    void _omitted;
    expect(() => validateBundle(bundle([withoutBounds as FlowRow]), 'v1')).toThrow('Faixa');
    expect(() =>
      validateBundle(
        bundle([
          { ...source, sensitivity: { lula: { min: 5, max: 1 }, flavio: { min: 0, max: 1 } } },
        ]),
        'v1',
      ),
    ).toThrow('Faixa');
    expect(
      validateBundle(bundle([{ ...source, sensitivity: null }]), 'v1').place.rows,
    ).toHaveLength(1);
  });
  it('rejects children that do not belong to the state bundle', () => {
    const misplaced = place([row('blank', 10, 3, 2)], 'SP:1');
    expect(() => validateBundle(bundle([row('blank', 100, 30, 20)], [misplaced]), 'v1')).toThrow(
      'Local inválido',
    );
    const unsupportedKind = { ...place([row('blank', 10, 3, 2)], 'MG:1:r:2'), kind: 'district' };
    expect(() =>
      validateBundle(
        bundle([row('blank', 100, 30, 20)], [unsupportedKind as unknown as Place]),
        'v1',
      ),
    ).toThrow('Local inválido');
  });
  it('rejects incomplete and repeated origins before a component can render them', () => {
    const source = row('blank', 100, 30, 20);
    const data = bundle([source]);
    expect(() => validateBundle(data, 'v1', ['blank', 'abstention'])).toThrow('incompletas');
    data.place.rows.push(source);
    expect(() => validateBundle(data, 'v1')).toThrow('repetidas');
  });
});
