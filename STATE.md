# Project snapshot

Eleições is a fixed personal research project exploring conditional ecological-inference estimates between Brazil's 2026 presidential election rounds. Individual vote transfers are not observed or identified. The interface is Brazilian Portuguese; source code and developer documentation are English.

## Implementation

- `pipeline/src/elections/` prepares the section panel, fits hierarchical constrained regression, reconciles sections by IPF, attributes movers, computes 12 sensitivity scenarios and accounting bounds, and exports the public dataset.
- `web/` is a static React/TypeScript/MapLibre explorer. Municipalities and foreign localities are the finest published geography.
- `data/sources.json` pins TSE and IBGE inputs. `data/specs/2026-v3.json` declares the analysis. Shared JSON Schemas define public format 2.0.
- A source-only checkout runs with explicitly labeled real-data fixtures. Detailed fixture coverage is Minas Gerais; complete national and state totals are retained.
- Dataset archives and checksums are generated outside Git. `data/releases.json` records actual packaged artifacts; restoration supports local archives and fixed HTTPS downloads.

## Validation

The README describes execution, data delivery, and interpretation. Versioned sources, specifications, schemas, and tests define the reproducible project.

- The original clean analysis/export provenance is preserved unchanged. Run `2026-v3-20261029-93230d180f36` contains all 12 scenarios; publication restores these computed results without claiming another refit.
- The generating computation source, original run metadata, and per-file hashes are preserved in the source capsule registered in `data/releases.json`. Its pipeline digest matches the published source independently of Git history.
- Source-only installation, all 55 Python tests, TypeScript, 28 frontend unit tests, Prettier, and the production build passed.
- Installed Google Chrome 156.0.8078.49 on the final compiled `/elections-check/` artifact: 48/48 passed on complete data; 46 passed and 2 foreign-locality cases skipped on the fixture. Both desktop and mobile viewports were tested.
- Full-schema and run-backed validation compared all 5,746 unique places and regenerated 30 resources byte-identically. Independent selected-matrix, export, bounds, and provenance probes passed on this final run.
- The complete archive contains 32 files and is 9,667,630 bytes. Local restoration recovered every file byte-identically and passed full-release validation. Its SHA-256 and relative artifact path are recorded in `data/releases.json`.
- Error recovery, single-request retries, parent navigation without geometry, and native map-resize handling have compiled-browser regression coverage. Source code and documentation contain no retired-project references or workstation paths.
- Essential project documentation is consolidated in the README. Local links, the restoration anchor, formatting, and an independent dependency review passed after consolidation.
- Caddy configuration, health routing, strict missing-resource responses, and MG/ZZ binary transport were checked locally. The production image requires the pinned complete archive and validates it before the frontend build.
- The public HTTPS site passed all 48 installed-Chrome cases. All 30 served dataset resources matched their manifest sizes and SHA-256 hashes. GitHub checks passed after publication.

## Interpretation limits

- Estimates are conditional on the specified model and aggregate section counts.
- The 12 sensitivity scenarios omit contextual heterogeneity; their range is not a confidence interval and understates specification uncertainty.
- Training and evaluation folds have been consulted repeatedly. Prediction scores are descriptive diagnostics, not confirmatory evidence of individual transfers.
- Identification bounds depend on the stated mobility assumptions and apply cell by cell; extremes need not occur together.
- Zero-origin shares are undefined. Missing geometry is distinct from an absent origin or electoral section.
- Geography identifies first-round polling locations, not residence. Boa Esperança do Norte has no polygon in the pinned mesh; overseas localities have no polygons.
- Chrome checks use temporary profiles and software WebGL. Physical-device, assistive-technology, Safari, and Firefox testing are outside the recorded validation.

## Distribution

- Publication repository: `https://github.com/Jalzn/inferencia-ecologica-votos`, with a single root commit named `initial commit`.
- Complete dataset and generating-source capsule: GitHub release `v0.1.0`. Both archives retain their SHA-256 checksums.
- Public address: `https://eleicoes.jalzn.com`, with DNS managed in Cloudflare and hosting on Railway. The provider address remains `https://elections-production-d9e6.up.railway.app`.
- The Dockerfile serves the complete static dataset through Caddy; service settings store the `/health` readiness check and port `8080` directly in Railway.
- A source-only checkout stages the labeled fixture. Raw inputs, runs, caches, and full generated data remain outside Git.
