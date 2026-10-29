import { useEffect, useMemo, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import { type GeoJSONSource, type Map as MapInstance } from 'maplibre-gl';
import type { FeatureCollection } from 'geojson';
import { bundleIdForPlace } from '../data/places';
import type { AreaBundle, DisplayGroup, Place } from '../data/types';
import { smallBaseShort } from '../results/copy';
import {
  balance,
  formatPercent,
  formatPoints,
  hasAssociatedSections,
  isSmallBase,
  share,
  summarize,
} from '../results/model';
import 'maplibre-gl/dist/maplibre-gl.css';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { gestureFocalPoint, zoomNavigationTarget, type ZoomGesture } from './zoomNavigation';

maplibregl.setWorkerUrl(workerUrl);

const empty: FeatureCollection = { type: 'FeatureCollection', features: [] };
const palette = [
  'interpolate',
  ['linear'],
  ['get', 'balance'],
  -1,
  '#346f9e',
  0,
  '#ece9e4',
  1,
  '#c14e5e',
];
const smallBasePattern = 'small-base-hatch';

/** Diagonal hatch, tiled seamlessly, that marks areas whose selected origin has a small base. */
function hatchImage() {
  const size = 16;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      if ((x + y) % 8 >= 2) continue;
      const index = (y * size + x) * 4;
      data.set([37, 57, 69, 165], index);
    }
  return { width: size, height: size, data };
}

export function geometryBounds(
  collection: FeatureCollection,
): [[number, number], [number, number]] | null {
  let west = Infinity,
    south = Infinity,
    east = -Infinity,
    north = -Infinity;
  function visit(value: unknown) {
    if (!Array.isArray(value)) return;
    if (typeof value[0] === 'number' && typeof value[1] === 'number') {
      west = Math.min(west, value[0]);
      east = Math.max(east, value[0]);
      south = Math.min(south, value[1]);
      north = Math.max(north, value[1]);
    } else value.forEach(visit);
  }
  for (const feature of collection.features) {
    if (feature.geometry && 'coordinates' in feature.geometry) visit(feature.geometry.coordinates);
  }
  return Number.isFinite(west)
    ? [
        [west, south],
        [east, north],
      ]
    : null;
}

type Props = {
  bundle: AreaBundle;
  selected: Place;
  group: DisplayGroup;
  onSelect: (id: string) => void;
  onZoomNavigate: (id: string) => boolean;
  zoomNavigationEnabled: boolean;
  requestedPlaceId: string;
  available: (id: string) => boolean;
};

export function ElectionMap({
  bundle,
  selected,
  group,
  onSelect,
  onZoomNavigate,
  zoomNavigationEnabled,
  requestedPlaceId,
  available,
}: Props) {
  const layerId = bundle.defaultLayer;
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapInstance | null>(null);
  const popup = useRef<maplibregl.Popup | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  const zoomCallback = useRef(onZoomNavigate);
  zoomCallback.current = onZoomNavigate;
  const pendingNavigation = useRef<{ id: string; bundleId: string } | null>(null);
  const cameraKey = useRef<string | null>(null);
  const gesture = useRef<ZoomGesture | null>(null);
  const fitCallback = useRef(fit);
  fitCallback.current = fit;
  const [cameraLocked, setCameraLocked] = useState(false);
  const interaction = useRef<{
    lock: (force?: boolean) => void;
    prepareFit: () => void;
    idle: () => void;
  } | null>(null);
  const current = useRef({ bundle, group });
  current.current = { bundle, group };
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [renderedKey, setRenderedKey] = useState<string | null>(null);
  const appliedKey = useRef<string | null>(null);
  const renderKey = `${bundle.datasetVersion}:${bundle.id}:${selected.id}:${group.id}`;
  const features = useMemo(() => {
    const places = new Map(bundle.children.map((place) => [place.id, place]));
    const collection = bundle.geometry[layerId] || empty;
    return {
      ...collection,
      features: collection.features.flatMap((feature) => {
        const id = String(feature.properties?.id);
        const place = places.get(id);
        if (!place) return [];
        const row = summarize(place, group);
        return [
          {
            ...feature,
            properties: {
              ...feature.properties,
              id,
              balance: balance(row) ?? 0,
              hasOrigin: row.observed > 0,
              hasSections: hasAssociatedSections(place),
              smallBase: isSmallBase(row.observed),
              selected: id === selected.id,
            },
          },
        ];
      }),
    } as FeatureCollection;
  }, [bundle, group, layerId, selected.id]);
  const featureRef = useRef(features);
  featureRef.current = features;
  const mappedIds = useMemo(
    () => new Set(features.features.map((feature) => String(feature.properties?.id))),
    [features],
  );
  const unmappedPlaces = useMemo(
    () =>
      bundle.children
        .filter((place) => !mappedIds.has(place.id))
        .sort((a, b) => a.name.localeCompare(b.name, 'pt-BR')),
    [bundle, mappedIds],
  );
  const fitKey = `${bundle.id}:${selected.id}`;
  const navigation = useRef({
    selected,
    fitKey,
    zoomNavigationEnabled,
    requestedPlaceId,
    renderKey,
  });
  navigation.current = { selected, fitKey, zoomNavigationEnabled, requestedPlaceId, renderKey };

  useEffect(() => {
    if (!pendingNavigation.current || requestedPlaceId !== pendingNavigation.current.id) {
      pendingNavigation.current = null;
      cameraKey.current = null;
    }
  }, [requestedPlaceId]);

  function fittedZoom(instance: MapInstance, collection: FeatureCollection): number {
    const bounds = geometryBounds(collection);
    if (!bounds) return NaN;
    if (bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]) return 14;
    return (
      instance.cameraForBounds(bounds, {
        padding: { top: 42, right: 40, bottom: 42, left: 40 },
        maxZoom: 16,
      })?.zoom ?? NaN
    );
  }

  useEffect(() => {
    if (!container.current) return;
    let instance: MapInstance;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: {
          version: 8,
          sources: {},
          layers: [
            { id: 'background', type: 'background', paint: { 'background-color': '#eef1f0' } },
          ],
        },
        center: [-52, -14],
        zoom: 2.6,
        maxZoom: 18,
        minZoom: 1.4,
        attributionControl: false,
        dragRotate: false,
        pitchWithRotate: false,
        renderWorldCopies: false,
        cooperativeGestures: false,
        locale: {
          'NavigationControl.ZoomIn': 'Aproximar mapa',
          'NavigationControl.ZoomOut': 'Afastar mapa',
          'Map.Title': 'Mapa das transferências estimadas',
        },
      });
    } catch {
      setFailed(true);
      return;
    }
    map.current = instance;
    instance.touchZoomRotate.disableRotation();
    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    instance.on('load', () => {
      instance.addImage(smallBasePattern, hatchImage(), { pixelRatio: 2 });
      instance.addSource('areas', { type: 'geojson', data: empty });
      instance.addLayer({
        id: 'area-fill',
        type: 'fill',
        source: 'areas',
        paint: {
          'fill-color': [
            'case',
            ['!', ['get', 'hasSections']],
            '#f8f9f6',
            ['get', 'hasOrigin'],
            palette,
            '#c8d1d6',
          ] as never,
          // Small bases mostly reproduce the regional pattern: weaken their color and hatch them.
          'fill-opacity': ['case', ['get', 'smallBase'], 0.45, 0.96],
        },
      });
      instance.addLayer({
        id: 'area-small-base',
        type: 'fill',
        source: 'areas',
        filter: ['==', ['get', 'smallBase'], true],
        paint: { 'fill-pattern': smallBasePattern },
      });
      instance.addLayer({
        id: 'area-line',
        type: 'line',
        source: 'areas',
        paint: {
          'line-color': ['case', ['get', 'selected'], '#253945', '#fffdf9'],
          'line-width': ['case', ['get', 'selected'], 2.5, 0.8],
        },
      });
      instance.addLayer({
        id: 'area-no-sections',
        type: 'line',
        source: 'areas',
        filter: ['!', ['get', 'hasSections']],
        paint: { 'line-color': '#9eacb2', 'line-width': 0.8, 'line-dasharray': [2, 2] },
      });
      setReady(true);
    });
    instance.on('idle', () => {
      setRenderedKey(appliedKey.current);
      interaction.current?.idle();
    });
    instance.on('movestart', () => setRenderedKey(null));
    let locked = false;
    let fitting = false;
    let destroyed = false;
    let lastInputAt = 0;
    let activeTouches = 0;
    let releaseTimer = 0;
    let clampQueued = false;
    const handlers = [
      instance.scrollZoom,
      instance.dragPan,
      instance.keyboard,
      instance.doubleClickZoom,
      instance.boxZoom,
      instance.touchZoomRotate,
    ];
    const originallyEnabled = handlers.map((handler) => handler.isEnabled());
    function diagnostics() {
      const frame = instance.getContainer().parentElement;
      if (!frame) return;
      frame.dataset.mapZoom = instance.getZoom().toFixed(4);
      frame.dataset.mapMinZoom = instance.getMinZoom().toFixed(4);
      frame.dataset.mapMaxZoom = instance.getMaxZoom().toFixed(4);
      frame.dataset.mapCenterLongitude = instance.getCenter().lng.toFixed(7);
      frame.dataset.mapCenterLatitude = instance.getCenter().lat.toFixed(7);
    }
    function controls(enabled: boolean) {
      const zoomIn = instance
        .getContainer()
        .querySelector<HTMLButtonElement>('.maplibregl-ctrl-zoom-in');
      const zoomOut = instance
        .getContainer()
        .querySelector<HTMLButtonElement>('.maplibregl-ctrl-zoom-out');
      // Refitting the same bounds can differ from the stored limit by floating-point noise.
      const zoomTolerance = 1e-6;
      if (zoomIn) {
        zoomIn.disabled =
          !enabled ||
          !featureRef.current.features.length ||
          instance.getZoom() >= instance.getMaxZoom() - zoomTolerance;
        zoomIn.setAttribute('aria-disabled', String(zoomIn.disabled));
      }
      // Keep the lower-level minus button available at its boundary to return to the parent.
      if (zoomOut) {
        zoomOut.disabled =
          !enabled ||
          (current.current.bundle.level === 'national' &&
            navigation.current.selected.id === current.current.bundle.id &&
            instance.getZoom() <= instance.getMinZoom() + zoomTolerance);
        zoomOut.setAttribute('aria-disabled', String(zoomOut.disabled));
      }
    }
    function geometryForSelection() {
      const collection = featureRef.current;
      const selectedFeatures = collection.features.filter(
        (feature) => feature.properties?.selected,
      );
      return selectedFeatures.length ? { ...collection, features: selectedFeatures } : collection;
    }
    function levelLimits() {
      const fitZoom = fittedZoom(instance, geometryForSelection());
      const leaf = navigation.current.selected.id !== current.current.bundle.id;
      return {
        fitZoom,
        min: Math.max(
          1.4,
          current.current.bundle.level === 'national' && !leaf ? fitZoom : fitZoom - 0.75,
        ),
        max: Math.min(16, leaf ? fitZoom + 2 : 16),
      };
    }
    function lock(force = false) {
      if (force) fitting = false;
      locked = true;
      setCameraLocked(true);
      handlers.forEach((handler) => handler.disable());
      controls(false);
      if (!fitting) {
        gesture.current = null;
        instance.stop();
      }
    }
    function releaseWhenReady() {
      window.clearTimeout(releaseTimer);
      if (
        destroyed ||
        !locked ||
        clampQueued ||
        activeTouches ||
        !navigation.current.zoomNavigationEnabled ||
        appliedKey.current !== navigation.current.renderKey ||
        !instance.getSource('areas') ||
        !instance.isSourceLoaded('areas') ||
        instance.isMoving()
      )
        return;
      const remaining = 220 - (performance.now() - lastInputAt);
      if (remaining > 0) {
        releaseTimer = window.setTimeout(releaseWhenReady, remaining + 1);
        return;
      }
      const limits = levelLimits();
      if (Number.isFinite(limits.fitZoom)) {
        instance.setMinZoom(limits.min);
        instance.setMaxZoom(limits.max);
      }
      fitting = false;
      locked = false;
      gesture.current = null;
      handlers.forEach((handler, index) => {
        if (originallyEnabled[index]) handler.enable();
      });
      instance.touchZoomRotate.disableRotation();
      controls(true);
      diagnostics();
      setCameraLocked(false);
    }
    function clampCamera(zoom: number, focal: [number, number], recenter = false) {
      if (clampQueued) return;
      clampQueued = true;
      const anchor = instance.unproject(focal);
      fitting = false;
      locked = true;
      setCameraLocked(true);
      handlers.forEach((handler) => handler.disable());
      gesture.current = null;
      controls(false);
      // HandlerManager cannot reset itself from inside its own camera-update callback.
      queueMicrotask(() => {
        if (destroyed) return;
        instance.stop();
        instance.setMinZoom(1.4);
        instance.setMaxZoom(18);
        if (recenter) {
          const bounds = geometryBounds(geometryForSelection());
          if (bounds)
            instance.fitBounds(bounds, {
              padding: { top: 42, right: 40, bottom: 42, left: 40 },
              duration: 0,
              maxZoom: 16,
            });
        } else instance.easeTo({ zoom, around: anchor, duration: 0 });
        clampQueued = false;
        diagnostics();
        controls(false);
        releaseWhenReady();
      });
    }
    function inspectGesture(directionOverride?: number, projectedZoom?: number) {
      const intent = gesture.current;
      const state = navigation.current;
      if (
        !intent ||
        locked ||
        !state.zoomNavigationEnabled ||
        pendingNavigation.current ||
        intent.selectionKey !== state.fitKey
      )
        return;
      const activeBundle = current.current.bundle;
      const collection = featureRef.current;
      const isChild = state.selected.id !== activeBundle.id;
      const parentId = isChild ? activeBundle.id : activeBundle.place.parentId;
      const limits = levelLimits();
      const delta = directionOverride ?? instance.getZoom() - intent.startZoom;
      const decisionZoom = projectedZoom ?? instance.getZoom();
      let candidate = null;
      if (!isChild && delta > 0 && instance.getLayer('area-fill')) {
        const hit = instance.queryRenderedFeatures(intent.focal, { layers: ['area-fill'] })[0];
        const id = hit?.properties?.id;
        const feature =
          typeof id === 'string' && collection.features.find((item) => item.properties?.id === id);
        if (feature)
          candidate = {
            id,
            fitZoom: fittedZoom(instance, { type: 'FeatureCollection', features: [feature] }),
          };
      }
      const target = zoomNavigationTarget({
        enabled: true,
        delta,
        zoom: decisionZoom,
        currentFitZoom: limits.fitZoom,
        parentId,
        candidate,
      });
      if (target && target !== state.selected.id) {
        const threshold =
          delta < 0 ? limits.min : Math.max(limits.fitZoom + 0.75, candidate!.fitZoom - 0.4);
        popup.current?.remove();
        if (Number.isFinite(threshold)) {
          // A municipality is a child of its state bundle; a state has its own bundle.
          pendingNavigation.current = { id: target, bundleId: bundleIdForPlace(target) ?? target };
          clampCamera(threshold, intent.focal);
        } else {
          // With no framing to preserve, let the destination fit its own geometry after loading.
          lock();
        }
        if (!zoomCallback.current(target)) {
          pendingNavigation.current = null;
          releaseWhenReady();
        }
        return;
      }
      const maximum = isChild
        ? limits.max
        : candidate
          ? Math.max(limits.fitZoom + 0.75, candidate.fitZoom - 0.4)
          : Math.min(16, limits.fitZoom + 2);
      if (delta > 0 && decisionZoom >= maximum) clampCamera(maximum, intent.focal);
      else if (
        delta < 0 &&
        activeBundle.level === 'national' &&
        !isChild &&
        decisionZoom <= limits.min + 0.002
      )
        clampCamera(limits.min, intent.focal, true);
    }
    function captureInput(event: Event) {
      if ('touches' in event) activeTouches = (event as TouchEvent).touches.length;
      const key = event instanceof KeyboardEvent ? event.key : '';
      const zoomKey = ['+', '=', '-', '_'].includes(key);
      const mapKey = zoomKey || key.startsWith('Arrow');
      const zoomControl =
        event.target instanceof Element &&
        event.target.closest('.maplibregl-ctrl-zoom-in, .maplibregl-ctrl-zoom-out');
      const wheel = event instanceof WheelEvent && event.deltaY !== 0;
      const pinch = 'touches' in event && activeTouches >= 2;
      const relevant =
        wheel ||
        pinch ||
        mapKey ||
        !!zoomControl ||
        event.type.startsWith('touch') ||
        event.type === 'pointerdown';
      if (relevant) lastInputAt = performance.now();
      if (locked) {
        if (event.type !== 'keydown' || mapKey) {
          if (event.cancelable) event.preventDefault();
          event.stopImmediatePropagation();
        }
        releaseWhenReady();
        return;
      }
      if (
        !navigation.current.zoomNavigationEnabled ||
        pendingNavigation.current ||
        !(wheel || pinch || zoomKey || (event.type === 'click' && zoomControl))
      )
        return;
      const focal = gestureFocalPoint(event, instance.getContainer());
      if (
        !gesture.current ||
        !instance.isZooming() ||
        gesture.current.selectionKey !== navigation.current.fitKey
      )
        gesture.current = {
          startZoom: instance.getZoom(),
          selectionKey: navigation.current.fitKey,
          focal,
        };
      else gesture.current.focal = focal;
      const direction = wheel
        ? -(event as WheelEvent).deltaY
        : zoomKey
          ? ['-', '_'].includes(key)
            ? -1
            : 1
          : zoomControl
            ? zoomControl.classList.contains('maplibregl-ctrl-zoom-out')
              ? -1
              : 1
            : 0;
      if (direction) {
        const step = Math.sign(direction);
        inspectGesture(step, zoomControl || zoomKey ? instance.getZoom() + step : undefined);
      }
      if (locked) {
        if (event.cancelable) event.preventDefault();
        event.stopImmediatePropagation();
      }
    }
    const inputTypes = [
      'wheel',
      'touchstart',
      'touchmove',
      'touchend',
      'touchcancel',
      'keydown',
      'click',
      'pointerdown',
    ];
    inputTypes.forEach((type) =>
      instance
        .getContainer()
        .addEventListener(type, captureInput, { capture: true, passive: false }),
    );
    instance.on('zoomstart', (event) => {
      if (locked) return;
      if (event.originalEvent && !gesture.current && navigation.current.zoomNavigationEnabled)
        gesture.current = {
          startZoom: instance.getZoom(),
          selectionKey: navigation.current.fitKey,
          focal: gestureFocalPoint(event.originalEvent, instance.getContainer()),
        };
    });
    instance.on('zoom', () => {
      diagnostics();
      inspectGesture();
    });
    instance.on('zoomend', () => {
      inspectGesture();
      if (!locked) gesture.current = null;
      controls(!locked);
    });
    interaction.current = {
      lock,
      prepareFit: () => {
        lock(true);
        fitting = true;
        instance.setMinZoom(1.4);
        instance.setMaxZoom(18);
      },
      idle: releaseWhenReady,
    };
    instance.on('click', 'area-fill', (event) => {
      if (!navigation.current.zoomNavigationEnabled) return;
      const id = event.features?.[0]?.properties?.id;
      const place = current.current.bundle.children.find((item) => item.id === id);
      popup.current?.remove();
      if (place) callback.current(place.id);
    });
    instance.on('mousemove', 'area-fill', (event) => {
      instance.getCanvas().style.cursor = 'pointer';
      if (event.originalEvent.buttons) return;
      const id = event.features?.[0]?.properties?.id;
      const place = current.current.bundle.children.find((item) => item.id === id);
      if (!place) return;
      const row = summarize(place, current.current.group);
      const box = document.createElement('div');
      box.className = 'map-tooltip';
      const name = document.createElement('strong');
      name.textContent = place.name;
      const origin = document.createElement('span');
      origin.className = 'map-tooltip-origin';
      origin.textContent = `${current.current.group.label} · 1º turno`;
      const detail = document.createElement('span');
      detail.textContent = !hasAssociatedSections(place)
        ? 'Sem seções de votação associadas'
        : row.observed
          ? `Lula ${formatPercent(share(row.estimated.lula, row.observed))} · Flávio ${formatPercent(share(row.estimated.flavio, row.observed))}`
          : 'Sem votos desta origem';
      box.append(name, origin, detail);
      const difference = balance(row);
      if (hasAssociatedSections(place) && difference !== null) {
        const delta = document.createElement('small');
        delta.textContent =
          difference === 0
            ? 'Diferença: 0 p.p. entre Lula e Flávio'
            : `${formatPoints(difference)} a mais para ${difference > 0 ? 'Lula' : 'Flávio'}`;
        box.append(delta);
      }
      if (isSmallBase(row.observed)) {
        const note = document.createElement('small');
        note.className = 'map-tooltip-small-base';
        note.textContent = smallBaseShort;
        box.append(note);
      }
      popup.current?.remove();
      popup.current = new maplibregl.Popup({ closeButton: false, offset: 12 })
        .setLngLat(event.lngLat)
        .setDOMContent(box)
        .addTo(instance);
    });
    instance.on('mouseleave', 'area-fill', () => {
      instance.getCanvas().style.cursor = '';
      popup.current?.remove();
    });
    let viewportWidth = instance.getContainer().clientWidth;
    let viewportHeight = instance.getContainer().clientHeight;
    function refitAfterResize() {
      const viewport = instance.getContainer();
      if (viewport.clientWidth === viewportWidth && viewport.clientHeight === viewportHeight)
        return;
      viewportWidth = viewport.clientWidth;
      viewportHeight = viewport.clientHeight;
      // MapLibre observes and redraws its container. Refit only after a real size change;
      // a second observer's redundant resize could clear readiness without another redraw.
      queueMicrotask(() => {
        if (!destroyed && navigation.current.zoomNavigationEnabled && !pendingNavigation.current)
          fitCallback.current();
      });
    }
    instance.on('resize', refitAfterResize);
    return () => {
      destroyed = true;
      window.clearTimeout(releaseTimer);
      inputTypes.forEach((type) =>
        instance.getContainer().removeEventListener(type, captureInput, true),
      );
      interaction.current = null;
      instance.off('resize', refitAfterResize);
      popup.current?.remove();
      markers.current.forEach((marker) => marker.remove());
      instance.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!zoomNavigationEnabled) interaction.current?.lock(true);
    else interaction.current?.idle();
  }, [zoomNavigationEnabled]);

  useEffect(() => {
    if (!ready || !map.current) return;
    interaction.current?.lock();
    map.current.setMinZoom(1.4);
    map.current.setMaxZoom(18);
    setRenderedKey(null);
    appliedKey.current = renderKey;
    (map.current.getSource('areas') as GeoJSONSource).setData(features);
  }, [ready, features, renderKey]);

  function fit() {
    const instance = map.current;
    if (!instance || !ready) return;
    gesture.current = null;
    pendingNavigation.current = null;
    const collection = featureRef.current;
    const selectedFeature = collection.features.filter((feature) => feature.properties?.selected);
    const target = selectedFeature.length
      ? { ...collection, features: selectedFeature }
      : collection;
    const bounds = geometryBounds(target);
    if (!bounds) return;
    interaction.current?.prepareFit();
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    instance.fitBounds(bounds, {
      padding: { top: 42, right: 40, bottom: 42, left: 40 },
      duration: reduced ? 0 : 350,
      maxZoom: 16,
    });
  }
  useEffect(() => {
    if (!ready || !zoomNavigationEnabled) return;
    if (
      pendingNavigation.current?.id === selected.id &&
      pendingNavigation.current.bundleId === bundle.id
    ) {
      pendingNavigation.current = null;
      cameraKey.current = fitKey;
      return;
    }
    if (pendingNavigation.current || cameraKey.current === fitKey) return;
    cameraKey.current = fitKey;
    fit();
  }, [ready, fitKey, zoomNavigationEnabled]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!ready || !map.current) return;
    markers.current.forEach((marker) => marker.remove());
    markers.current = [];
    const polygons = (bundle.geometry[layerId] || empty).features.filter(
      (feature) =>
        feature.geometry?.type === 'Polygon' || feature.geometry?.type === 'MultiPolygon',
    );
    polygons.sort(
      (a, b) => Number(b.properties?.id === selected.id) - Number(a.properties?.id === selected.id),
    );
    const isNational = bundle.level === 'national';
    if (!isNational && polygons.length > 36) return;
    for (const feature of polygons) {
      const bounds = geometryBounds({ type: 'FeatureCollection', features: [feature] });
      if (!bounds) continue;
      const label = document.createElement('span');
      label.className = isNational ? 'state-label' : 'area-label';
      label.textContent = String(
        isNational ? feature.properties?.id || '' : feature.properties?.name || '',
      );
      label.setAttribute('aria-hidden', 'true');
      markers.current.push(
        new maplibregl.Marker({ element: label })
          .setLngLat([(bounds[0][0] + bounds[1][0]) / 2, (bounds[0][1] + bounds[1][1]) / 2])
          .addTo(map.current),
      );
    }
    if (isNational) return;
    const instance = map.current;
    let frame = 0;
    function avoidCollisions() {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const viewport = container.current?.getBoundingClientRect();
        if (!viewport) return;
        const occupied: DOMRect[] = [];
        for (const marker of markers.current) {
          const label = marker.getElement();
          const bounds = label.getBoundingClientRect();
          const outside =
            bounds.left < viewport.left + 5 ||
            bounds.right > viewport.right - 5 ||
            bounds.top < viewport.top + 5 ||
            bounds.bottom > viewport.bottom - 5;
          const overlap = occupied.some(
            (other) =>
              bounds.left < other.right + 3 &&
              bounds.right > other.left - 3 &&
              bounds.top < other.bottom + 3 &&
              bounds.bottom > other.top - 3,
          );
          label.style.visibility = outside || overlap ? 'hidden' : 'visible';
          if (!outside && !overlap) occupied.push(bounds);
        }
      });
    }
    instance.on('move', avoidCollisions);
    instance.on('resize', avoidCollisions);
    avoidCollisions();
    return () => {
      cancelAnimationFrame(frame);
      instance.off('move', avoidCollisions);
      instance.off('resize', avoidCollisions);
    };
  }, [ready, bundle, layerId, selected.id]);

  const noGeometry = !features.features.length;
  const selectedUnmapped = selected.id !== bundle.place.id && !mappedIds.has(selected.id);
  const placeButton = (place: Place, suffix = '') => (
    <li key={place.id}>
      <button
        type="button"
        aria-current={place.id === selected.id ? 'location' : undefined}
        aria-disabled={!available(place.id)}
        onClick={() => available(place.id) && onSelect(place.id)}
      >
        <span>
          {place.name}
          {suffix}
        </span>
        {!available(place.id) && <em>Base completa</em>}
      </button>
    </li>
  );
  return (
    <div
      className="map-frame"
      data-testid="election-map"
      data-map-ready={ready && renderedKey === renderKey ? 'true' : 'false'}
      data-map-locked={cameraLocked ? 'true' : 'false'}
    >
      <div
        className="map-canvas"
        ref={container}
        role="region"
        aria-label={`Mapa de ${bundle.place.name}, saldo estimado da origem ${group.label}`}
      />
      <button
        className="map-fit"
        type="button"
        onClick={fit}
        aria-label="Reenquadrar mapa"
        title="Reenquadrar mapa"
        disabled={cameraLocked || noGeometry}
      >
        ⌖
      </button>
      {cameraLocked && ready && (
        <div className="map-transition-status" role="status">
          Preparando mapa…
        </div>
      )}
      {(failed || noGeometry) && (
        <div className="map-empty" data-testid="map-empty">
          <span aria-hidden="true">◎</span>
          <strong>
            {failed
              ? 'Mapa indisponível neste navegador'
              : bundle.id === 'ZZ'
                ? 'Localidades no exterior não têm limites no mapa'
                : 'Sem geometria disponível'}
          </strong>
          <p>
            {failed
              ? 'Você pode continuar pela busca e consultar todas as estimativas na lista.'
              : 'Escolha um lugar abaixo ou pela busca. As estimativas aparecem na lista de origens.'}
          </p>
          {!failed && unmappedPlaces.length > 0 && (
            <ul className="unmapped-list" aria-label="Lugares sem limite no mapa">
              {unmappedPlaces.map((place) => placeButton(place))}
            </ul>
          )}
        </div>
      )}
      {!failed && !noGeometry && (selectedUnmapped || unmappedPlaces.length > 0) && (
        <div className="map-notes">
          {selectedUnmapped && (
            <p className="map-note" data-testid="no-geometry-note" role="status">
              <strong>{selected.name}</strong> não tem limite na malha territorial usada. As
              estimativas continuam na lista de origens.
            </p>
          )}
          {unmappedPlaces.length === 1 && unmappedPlaces[0].id !== selected.id && (
            <ul className="unmapped-places" data-testid="unmapped-places">
              {placeButton(unmappedPlaces[0], ' · fora do mapa')}
            </ul>
          )}
          {unmappedPlaces.length > 1 && (
            <details className="unmapped-places" data-testid="unmapped-places">
              <summary>Fora do mapa ({unmappedPlaces.length})</summary>
              <ul aria-label="Lugares sem limite no mapa">
                {unmappedPlaces.map((place) => placeButton(place))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
