import { describe, expect, it } from 'vitest';
import { zoomNavigationTarget, type ZoomNavigationInput } from '../src/map/zoomNavigation';

const state: ZoomNavigationInput = {
  enabled: true,
  delta: 1,
  zoom: 9.6,
  currentFitZoom: 6,
  parentId: 'BR',
  candidate: { id: 'MG:41238', fitZoom: 10 },
};

describe('Geographic zoom hysteresis', () => {
  it('enters a target only when both parent and target framing thresholds are met', () => {
    expect(zoomNavigationTarget({ ...state, zoom: 9.59 })).toBeNull();
    expect(zoomNavigationTarget(state)).toBe('MG:41238');
    expect(
      zoomNavigationTarget({ ...state, zoom: 6.74, candidate: { id: 'large', fitZoom: 6.5 } }),
    ).toBeNull();
    expect(
      zoomNavigationTarget({ ...state, zoom: 6.75, candidate: { id: 'large', fitZoom: 6.5 } }),
    ).toBe('large');
  });

  it('returns one parent on zoom out and leaves a stable gap around its own fitted view', () => {
    expect(zoomNavigationTarget({ ...state, delta: -1, zoom: 5.26 })).toBeNull();
    expect(zoomNavigationTarget({ ...state, delta: -1, zoom: 5.25 })).toBe('BR');
    expect(zoomNavigationTarget({ ...state, delta: -1, zoom: 5.250000001 })).toBe('BR');
    expect(zoomNavigationTarget({ ...state, delta: -1, zoom: 5.25, parentId: null })).toBeNull();
  });

  it('does not descend while zooming out or go up while zooming in', () => {
    expect(zoomNavigationTarget({ ...state, delta: -1, zoom: 12 })).toBeNull();
    expect(zoomNavigationTarget({ ...state, zoom: 4 })).toBeNull();
  });

  it('returns the parent of an unframed place only on an enabled zoom-out gesture', () => {
    const unframed = { ...state, currentFitZoom: NaN, delta: -1 };
    expect(zoomNavigationTarget(unframed)).toBe('BR');
    expect(zoomNavigationTarget({ ...unframed, parentId: null })).toBeNull();
    expect(zoomNavigationTarget({ ...unframed, enabled: false })).toBeNull();
    expect(zoomNavigationTarget({ ...unframed, delta: -0.01 })).toBeNull();
    expect(zoomNavigationTarget({ ...unframed, delta: 1 })).toBeNull();
  });

  it('leaves leaf and ambiguous or missing targets unchanged', () => {
    expect(zoomNavigationTarget({ ...state, candidate: null, zoom: 16 })).toBeNull();
    expect(
      zoomNavigationTarget({ ...state, candidate: { id: 'missing', fitZoom: NaN } }),
    ).toBeNull();
  });

  it('ignores loading, programmatic/no-intent, tiny deltas, and unframed geometry', () => {
    expect(zoomNavigationTarget({ ...state, enabled: false })).toBeNull();
    expect(zoomNavigationTarget({ ...state, delta: 0 })).toBeNull();
    expect(zoomNavigationTarget({ ...state, delta: 0.01 })).toBeNull();
    expect(zoomNavigationTarget({ ...state, currentFitZoom: NaN })).toBeNull();
  });
});
