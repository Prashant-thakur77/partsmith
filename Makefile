# PartSmith — every target works with zero API keys (missing keys switch providers to deterministic mocks).
SHELL := /bin/bash
.DEFAULT_GOAL := help
UV ?= uv
PNPM ?= pnpm
API_PORT ?= 8000
WEB_PORT ?= 3000

.PHONY: help setup sync web-install schemas test test-all test-web lint typecheck check smoke dev api web worker \
        seed synth bench bench-live live lie mat mcp e2e clean-var gitleaks deploy-check

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

setup: sync web-install schemas ## Install Python + web deps, generate types
	@test -f .env || cp .env.example .env

sync: ## Install the Python environment (uv, Python 3.12)
	$(UV) sync --python 3.12 --all-extras

web-install: ## Install web dependencies
	$(PNPM) install

schemas: ## Export JSON Schema + TypeScript types from the Pydantic contracts
	$(UV) run python -m partsmith_schemas.export

test: ## Fast unit tests (no network, no keys)
	$(UV) run pytest -m "not slow and not live"

test-all: ## All Python tests including slow geometry tests
	$(UV) run pytest -m "not live"

test-web: ## Web typecheck, lint, build, e2e
	$(PNPM) -C apps/web typecheck && $(PNPM) -C apps/web lint && $(PNPM) -C apps/web test && $(PNPM) -C apps/web build && $(PNPM) -C apps/web e2e

lint: ## Ruff
	$(UV) run ruff check services eval tools packages/schemas
	$(UV) run ruff format --check services eval tools packages/schemas

typecheck: ## mypy --strict
	$(UV) run mypy services eval tools packages/schemas/partsmith_schemas

check: lint typecheck test ## Lint + types + tests

smoke: ## One call per provider: ✅ live ok · ⚠️ key missing (mock) · ❌ live failed
	$(UV) run python -m tools.smoke

seed: ## Build demo parts + synthetic sample runs into the registry ($$PARTSMITH_HOME)
	$(UV) run partsmith seed

synth: ## Regenerate the synthetic bench (exact ground truth, deterministic from the seed)
	$(UV) run python -m tools.synth --out data/synthetic/bench --n 200 --seed 7 --n-reference 20 --jobs 6

bench: ## Regenerate eval reports from stored runs (no keys needed)
	$(UV) run python -m eval.run --from-runs
	$(UV) run python -m tools.readme

bench-live: ## Re-run every bench with the providers configured in .env
	$(UV) run python -m eval.run --live
	$(UV) run python -m tools.readme

live: ## Check keys, then re-run the benches live
	$(UV) run python -m tools.smoke && PROVIDER_MODE=live $(MAKE) bench-live

# eval.bypass --demo exits 3 when the export gate refuses the lie: here that refusal is the success case, so the target
# reports it and exits 0. Any other exit (0 = the lie got through, 1 = harness error) fails the target.
lie: ## Terminal demo (seconds, no keys): a model claims VERIFIED on a wrong part; code refuses the export
	@$(UV) run python -m eval.bypass --demo says_verified; code=$$?; \
	if [ $$code -eq 3 ]; then echo "make lie: OK. eval.bypass exited 3 = export refused, which is the expected outcome."; \
	else echo "make lie: FAILED. eval.bypass exited $$code (0 = the lie got through, 1 = harness error)."; exit 1; fi

mat: ## Write the plain-paper mat PDF + web mat layouts
	$(UV) run python -m tools.mat.make_mat --pdf var/partsmith-mat-a4.pdf --web

api: ## FastAPI on :$(API_PORT)
	$(UV) run uvicorn services.api.main:app --port $(API_PORT) --reload --reload-dir services --reload-dir packages

web: ## Next.js on :$(WEB_PORT)
	API_URL=http://localhost:$(API_PORT) $(PNPM) -C apps/web dev --port $(WEB_PORT)

mcp: ## MCP server over stdio
	$(UV) run python -m services.mcp.server

dev: ## API + web together (Ctrl-C stops both)
	@$(UV) run partsmith seed --if-empty
	@trap 'kill 0' INT TERM EXIT; $(MAKE) --no-print-directory api & $(MAKE) --no-print-directory web & wait

e2e: ## Playwright e2e for the web app
	$(PNPM) -C apps/web e2e

deploy-check: ## Static checks of infra/deploy (no image build, no deploy; see infra/deploy/README.md)
	$(UV) run python infra/deploy/check.py

gitleaks: ## Secret scan of the git history + working tree
	gitleaks git --no-banner --redact . && gitleaks dir --no-banner --redact .

clean-var: ## Delete local runtime data (var/)
	rm -rf var
