# Eleições engineering instructions

## Language and scope

Write code, filenames, identifiers, comments, docstrings, tests, commit messages, and developer documentation in English. User-facing copy is Brazilian Portuguese; preserve official proper names. The product explores conditional ecological-inference estimates, not observed individual vote transfers.

Read `README.md` and the normative JSON Schemas in `data/schemas/` before changing data or UI. Keep all implementation work inside this repository.

## Architecture

`web/` is a React/TypeScript/Vite application with MapLibre. `pipeline/` is a Python package for data preparation, inference utilities, validation, and public export. `data/schemas/` defines the shared contract. Large generated files are not Git source. A clean clone must build and test with explicitly labeled real-data fixtures; a production release must require its complete dataset.

Do not recalculate statistical estimates in the browser. Presentation aggregations must preserve denominators and all five destinations. Keep observed counts, model estimates, sensitivity ranges, and identification bounds distinct. Never sum sensitivity endpoints across origins as a claimed exact range. Zero-origin shares are undefined. Geography describes first-round polling locations, not residence. Layers and their residuals are separate partitions, not additive across layers.

## Collaboration and validation

Use bounded subagents for independent tasks. Assign disjoint write scopes. An adversarial reviewer must be different from the author of the component reviewed. Keep validation claims reproducible. Agreement between agents is not statistical identification.

Run relevant numerical, contract, TypeScript, UI, and browser checks. Browser validation must use installed Google Chrome for this implementation. Keep browser profiles temporary; do not use personal sessions. Never fabricate passing test results or claim national model refitting when only exporting existing estimates.

Keep source and generated data versions explicit. Do not publish, upload datasets, or configure a remote as part of local implementation unless requested. Update `STATE.md` with completed work, validation, and remaining limitations.
