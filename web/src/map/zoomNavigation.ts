export type ZoomCandidate = { id: string; fitZoom: number };
export type ZoomNavigationInput = {
  enabled: boolean;
  delta: number;
  zoom: number;
  currentFitZoom: number;
  parentId: string | null;
  candidate: ZoomCandidate | null;
};

/** Hysteresis keeps adjacent geographic views from oscillating near a boundary. */
export function zoomNavigationTarget(input: ZoomNavigationInput): string | null {
  if (!input.enabled || Math.abs(input.delta) < 0.02) return null;
  // Places without polygons still have a geographic parent, but no camera threshold.
  if (!Number.isFinite(input.currentFitZoom)) return input.delta < 0 ? input.parentId : null;
  if (input.delta < 0) {
    return input.parentId && input.zoom <= input.currentFitZoom - 0.75 + 0.001
      ? input.parentId
      : null;
  }
  if (!input.candidate || !Number.isFinite(input.candidate.fitZoom)) return null;
  const threshold = Math.max(input.currentFitZoom + 0.75, input.candidate.fitZoom - 0.4);
  return input.zoom >= threshold - 0.001 ? input.candidate.id : null;
}

export type ZoomGesture = { startZoom: number; selectionKey: string; focal: [number, number] };

/** Controls/keyboard use the center; wheel and pinch retain their geographic focal point. */
export function gestureFocalPoint(
  event: Event | undefined,
  container: HTMLElement,
): [number, number] {
  const bounds = container.getBoundingClientRect();
  const center: [number, number] = [bounds.width / 2, bounds.height / 2];
  if (!event || (event.target instanceof Element && event.target.closest('.maplibregl-ctrl')))
    return center;
  if ('touches' in event) {
    const touchEvent = event as TouchEvent;
    const touches = touchEvent.touches.length ? touchEvent.touches : touchEvent.changedTouches;
    if (!touches.length) return center;
    const points = Array.from(touches);
    return [
      points.reduce((sum, touch) => sum + touch.clientX, 0) / points.length - bounds.left,
      points.reduce((sum, touch) => sum + touch.clientY, 0) / points.length - bounds.top,
    ];
  }
  if ('clientX' in event && 'clientY' in event)
    return [
      (event as MouseEvent).clientX - bounds.left,
      (event as MouseEvent).clientY - bounds.top,
    ];
  return center;
}
