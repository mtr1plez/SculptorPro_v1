.PHONY: install install-backend install-ui run-backend run-ui start lint test clean

PYTHON ?= python3
PIP ?= $(PYTHON) -m pip
NPM ?= npm
UVICORN ?= $(PYTHON) -m uvicorn

install: install-backend install-ui

install-backend:
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install-ui:
	cd ui && $(NPM) install

run-backend:
	PYTHONPATH=. $(UVICORN) src.api.server:app --host 127.0.0.1 --port 8000 --reload

run-ui:
	cd ui && $(NPM) run dev:electron

start:
	./SculptorPro.sh

lint:
	$(PYTHON) -m ruff check src
	cd ui && $(NPM) run lint

test:
	PYTHONPATH=. $(PYTHON) -m pytest src/tests

clean:
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	rm -rf ui/dist
