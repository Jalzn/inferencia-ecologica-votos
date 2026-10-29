# Eleições web explorer

React, TypeScript, Vite, and MapLibre present a fixed dataset of conditional ecological-inference estimates. Interface text is Brazilian Portuguese; code and developer documentation are English.

Run these commands from `web/`:

```sh
npm ci
npm run dev
npm test
npm run format:check
npm run build
npm run test:browser
```

The preparation hook preserves an existing `public/data/` dataset. If its manifest is absent, it stages the real-data fixture from `../data/fixtures/public`: national and state totals plus Minas Gerais municipality detail. A persistent banner identifies this limited coverage. Complete publication requires `scope: full`; see [dataset restoration](../README.md#restore-the-complete-dataset).

## Build and browser checks

Set `BASE_PATH` to the repository path when building for a project URL. Resources and shared selections respect that path. Check the compiled artifact under a project prefix with:

```sh
BASE_PATH=/elections-check/ npm run build
BASE_PATH=/elections-check/ E2E_PREVIEW=1 npm run test:browser
```

Preview mode serves the existing `dist/` artifact without preparing or replacing its dataset. `E2E_BASE_URL` can target a running server; otherwise Playwright starts a local server on port 4173. Tests use installed Google Chrome (`channel: chrome`), temporary browser profiles, desktop and mobile viewports, and axe accessibility checks. Software WebGL rendering supports headless checks; its timing is not a physical-device performance benchmark.

## Data and scientific presentation

The loader verifies schema compatibility, resource sizes, SHA-256, row completeness, and conservation. Gzip payloads have `.json.bin` paths and are decoded after integrity verification. An LRU cache limits decoded-text storage. The browser does not refit statistical estimates.

National and state bundles load by territory. Municipalities and overseas localities are children of their state bundle, so selecting another municipality inside an open state reuses its data. A link names a place and a display group. Unknown places produce a recoverable error; raw null-vote origin links select the combined Nulos group.

Display groups preserve the full observed denominator and all five estimated destinations. Grouped uncertainty ranges remain unavailable rather than summing marginal endpoints. The detail dialog uses the manifest's sensitivity and identification-bounds descriptions. Integer percentages use «<1%» and «>99%» at the extremes. An origin with 1–99 voters is labeled as a small base and hatched on the map; an absent origin and an area with no associated sections remain distinct conditions.

## Map and navigation

Fonts and geometry are supplied locally, with a neutral map style and no remote basemap or provider key. Search and results remain usable when WebGL cannot initialize. Places without polygons stay listed and selectable, including overseas localities and a municipality absent from the pinned mesh.

The desktop view combines map and origin sidebar; mobile uses a compact origin launcher and dialog sheet. Search, breadcrumbs, sharing, methodology, and help sit within the map area. Keyboard focus returns to the origin launcher after the mobile sheet closes.

Wheel and pinch gestures use their geographic focal point. Buttons and keyboard use the map center. Zooming changes the selection through Brazil, state, and municipality levels. Fit-relative thresholds and hysteresis allow at most one geographic transition per gesture. Programmatic fits from search, history, resize, or recentering do not trigger geographic navigation.

At a data transition, the camera waits for the requested bundle and for the gesture to end. Search can cancel a slow request; a failed request offers recovery. The national view has a fitted lower zoom bound, and municipality views have an upper bound. The zoom-out control returns to the parent even when the selected place has no polygon.
