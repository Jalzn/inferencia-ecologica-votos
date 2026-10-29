/**
 * Place addressing. Municipalities and foreign localities are children of their
 * state bundle (`MG:41238` lives in `MG`, `ZZ:29254` in `ZZ`); there is no municipality bundle.
 */

export const nationalId = 'BR';

/** The place a shared link names, or Brazil when it names none. */
export function canonicalPlaceId(raw: string | null | undefined): string {
  return (raw || '').trim() || nationalId;
}

/** The bundle that contains a place: `BR` for Brazil, otherwise the two-letter state code. */
export function bundleIdForPlace(id: string): string | null {
  if (id === nationalId) return nationalId;
  const match = /^([A-Z]{2})(?::[^:]+)?$/.exec(id);
  return match ? match[1] : null;
}
