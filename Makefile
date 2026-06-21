# SolarVolt — developer entry points (plan.md §13).
# `make dev` is the one-command working-copy run: backend + frontend on the dummy,
# no hardware. Everything here works straight after `git pull`.

PYTHON ?= python3
VENV   := .venv
# Absolute paths so `cd backend && $(PY)` doesn't trip Python's relative-prefix warning.
PY     := $(CURDIR)/$(VENV)/bin/python
PIP    := $(CURDIR)/$(VENV)/bin/pip

.PHONY: help install install-backend install-frontend dev backend-dev frontend-dev \
        build test test-backend test-frontend e2e clean install-service uninstall-service

help:
	@echo "make install        - venv + backend deps + frontend deps"
	@echo "make dev            - run backend (:8000) + frontend (:4200) together"
	@echo "make test           - backend (pytest+cov) + frontend (vitest)"
	@echo "make build          - production frontend build (served by the backend)"
	@echo "make e2e            - Playwright end-to-end suite (needs 'make build' first)"
	@echo "make install-service   - native install: systemd service on this host (needs sudo)"
	@echo "make uninstall-service - remove the systemd service (needs sudo)"

install: install-backend install-frontend

install-backend:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt

install-frontend:
	cd frontend && npm install

# Run both tiers; Ctrl-C stops the whole process group.
dev:
	@echo ">> backend http://localhost:8000   frontend http://localhost:4200"
	@trap 'kill 0' EXIT; \
	( cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000 ) & \
	( cd frontend && npm start ) & \
	wait

backend-dev:
	cd backend && $(PY) -m uvicorn app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm start

build:
	cd frontend && npm run build

test: test-backend test-frontend

# 80% overall is the §21 floor; critical-logic modules are held higher in review.
test-backend:
	cd backend && $(PY) -m pytest --cov-fail-under=80

test-frontend:
	cd frontend && CI=true npm test -- --watch=false

e2e:
	cd e2e && npm test

clean:
	rm -rf frontend/dist backend/.pytest_cache .pytest_cache backend/.coverage
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +

# Native production install on this host (Raspberry Pi / Ubuntu) — systemd service that
# serves the built UI + API on :8000 and survives reboots. See plan.md §13.
install-service:
	sudo ./install.sh

uninstall-service:
	sudo ./uninstall.sh
