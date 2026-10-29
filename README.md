# Eleições

[Explorer](https://eleicoes.jalzn.com) · [GitHub](https://github.com/Jalzn/inferencia-ecologica-votos) · [Complete dataset](https://github.com/Jalzn/inferencia-ecologica-votos/releases/tag/v0.1.0)

A personal research project mapping conditional ecological-inference estimates between Brazil's 2026 presidential election rounds. Explore first-round origins and their estimated second-round destinations at national, state, municipality, and overseas-locality levels.

The interface is in Brazilian Portuguese. Code, tests, and developer documentation are in English. The estimates describe a statistical model fitted to aggregate section counts; individual vote transfers are not observed or identified.

## Run locally

Requirements: Node.js 22.12 or newer, npm, Python 3.12, and uv. Browser checks use installed Google Chrome.

```bash
make setup
make dev
```

Open the local URL printed by Vite. A source-only clone automatically stages the small real-data fixture: national totals, all state rows, and municipality detail for Minas Gerais. The interface labels this limited coverage. Startup and build commands preserve an existing dataset in `web/public/data/`.

Complete results are delivered as a separate fixed dataset archive. Its version, SHA-256, and actual artifact location are recorded in [the release registry](data/releases.json). The source repository alone does not contain the complete export.

## Project structure

```text
web/         React, TypeScript, Vite, and MapLibre explorer
pipeline/    Python preparation, inference, analysis, validation, and export
data/        Source registry, specification, schemas, fixtures, and release index
scripts/     Dataset packaging and restoration
.github/     Source-only checks
```

The [JSON Schemas](data/schemas/) define public format 2.0, separating observed counts, estimates, sensitivity ranges, identification bounds, and geographic coverage. Statistical computation belongs to the Python pipeline; the browser presents the exported results.

## Verify this version

```bash
make test
BASE_PATH=/elections-check/ make build
BASE_PATH=/elections-check/ E2E_PREVIEW=1 make test-browser
```

The Python and frontend tests use controlled inputs and explicitly labeled fixtures. The browser checks exercise the compiled artifact in Chrome at desktop and mobile sizes. Verification establishes computational properties, not the true individual transitions.

## Reproduce the complete dataset

Use a committed, unmodified source revision for a publishable result:

```bash
make sources
make analyze
# Replace RUN_ID with the run identifier printed by the analysis.
RUN=data/runs/RUN_ID
make export-data RUN="$RUN"
make package-release RUN="$RUN"
```

`make sources SOURCE_MIRRORS="directory ..."` can use local copies after verifying their pinned hashes in [the source registry](data/sources.json). The [analysis specification](data/specs/2026-v3.json) declares candidate models, folds, scenarios, and assumptions. Packaging validates every resource against the run and source data, requires complete coverage and clean code provenance, and records the archive and checksum in the release registry. Raw inputs, runs, and generated exports remain outside Git.

## Restore the complete dataset

After `make setup`, set `DATASET_ARCHIVE` to the complete archive path and `DATASET_SHA256` to its checksum from the release registry:

```bash
.venv/bin/python scripts/release_tools.py restore \
  --archive "$DATASET_ARCHIVE" \
  --sha256 "$DATASET_SHA256" \
  --output web/public/data
.venv/bin/python -m elections.cli validate-release \
  --release web/public/data --require-full --deep-schema
make build
```

Restore before startup stages a fixture. Restoration refuses to replace an existing directory; move an existing generated `web/public/data/` directory aside deliberately. The checksum is verified before extraction. A hosted archive can instead be restored with `fetch --url "$DATASET_URL" --sha256 "$DATASET_SHA256" --output web/public/data` using the same script and a real HTTPS URL.

The [GitHub release](https://github.com/Jalzn/inferencia-ecologica-votos/releases/tag/v0.1.0) distributes the complete archive, checksums, and a capsule of its generating computation source. Original analysis provenance is preserved unchanged. The capsule and its pipeline content digest identify the generating source independently of the publication repository's single-commit history. A reproduction under a different Git revision receives a different run identifier.

## Railway hosting

The root `Dockerfile` downloads the fixed complete dataset, verifies its checksum and full schema, and builds the explorer at `/`. The runtime serves static files through Caddy on Railway's `PORT`, with `/health` for deployment checks. A missing or invalid dataset fails the build; production does not fall back to the fixture.

Create a Railway service from this repository's `main` branch using the root directory. Railway detects the Dockerfile; set the service healthcheck to `/health` with a 60-second timeout and the public target port to `8080`. The published service stores these settings directly in Railway. `DATASET_URL` and `DATASET_SHA256` are optional build arguments for another complete, validated release. Railway provides public HTTPS; no inference service, database, or persistent volume is required.

## Method

The pipeline fits national, state, and municipal transition matrices by constrained regression on section-level shares. Rows are nonnegative and sum to one. State matrices shrink toward the national matrix; municipal matrices shrink toward their state. Municipal regularization is selected by aggregate prediction on declared validation folds.

Section tables are reconciled to observed margins by iterative proportional fitting. Voters changing sections retain their first-round geography, with destinations attributed through an explicit national pairing assumption. Municipality, state, and national flows are sums of section flows; shares are ratios of sums.

Sensitivity endpoints are the minimum and maximum of each place's aggregated flow across 12 scenarios varying geographic pooling, mobility, and probability floors. Identification bounds use section counts under a fixed-electorate assumption and section-level mobility capped by the largest declared scenario.

## Interpretation and limitations

- Percentages use the full first-round origin, including second-round blank, null, and abstention destinations.
- The 12 sensitivity specifications share a within-municipality homogeneity assumption. Their range is not a confidence interval and omits contextual heterogeneity.
- Validation and holdout folds were consulted during model development. Prediction scores are diagnostics, not confirmatory evidence of individual transitions.
- Identification bounds are cellwise accounting limits under declared mobility assumptions. Their extremes need not occur together.
- Shares for a zero origin count are undefined; missing geometry is a separate condition.
- Geography describes first-round polling locations, not residence. Overseas voting is included and labeled separately.
- The pinned IBGE mesh lacks a polygon for Boa Esperança do Norte. Overseas localities also have no polygons; all remain listed and selectable.

This repository is a fixed personal research snapshot.

The [MIT license](LICENSE) applies to the code. Source datasets and geographic products retain their original terms and attribution. [CITATION.cff](CITATION.cff) identifies the software; report the dataset version alongside any result.
