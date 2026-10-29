PYTHON ?= .venv/bin/python
NPM ?= npm
RAW_ROOT ?= data/raw/2026
SOURCE_MIRRORS ?=
RUN ?=
RELEASE_ARCHIVE ?= data/releases/elections-$(notdir $(RUN)).tar.gz
-include .local.mk

.PHONY: setup dev test test-python test-web test-browser build sources analyze \
	validate-data export-data export-fixture package-release require-run

setup:
	UV_PROJECT_ENVIRONMENT="$(abspath .venv)" uv sync --project pipeline --locked --python 3.12
	$(NPM) --prefix web ci

dev:
	$(NPM) --prefix web run dev

test: test-python test-web

test-python:
	$(PYTHON) -m unittest discover -s pipeline/tests -v

test-web:
	$(NPM) --prefix web run typecheck
	$(NPM) --prefix web run format:check
	$(NPM) --prefix web test

test-browser:
	$(NPM) --prefix web run test:browser

build:
	$(NPM) --prefix web run build

sources:
	$(PYTHON) -m elections.cli sources fetch --raw-root "$(RAW_ROOT)" $(foreach mirror,$(SOURCE_MIRRORS),--mirror "$(mirror)")

analyze:
	$(PYTHON) -m elections.cli analyze --raw-root "$(RAW_ROOT)"

require-run:
	@test -n "$(RUN)" || (echo "Set RUN=data/runs/<run-id> (printed by make analyze)" && exit 1)

validate-data: require-run
	$(PYTHON) -m elections.cli validate-release --release web/public/data --require-full --deep-schema \
		--run "$(RUN)" --raw-root "$(RAW_ROOT)"

export-data: require-run
	$(PYTHON) -m elections.cli export --run "$(RUN)" --raw-root "$(RAW_ROOT)" --output web/public/data --overwrite

export-fixture: require-run
	$(PYTHON) -m elections.cli export --run "$(RUN)" --raw-root "$(RAW_ROOT)" --output data/fixtures/public --fixture --overwrite

package-release: validate-data
	$(PYTHON) scripts/release_tools.py pack --directory web/public/data --output "$(RELEASE_ARCHIVE)" --index data/releases.json
