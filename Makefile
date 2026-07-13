.PHONY: setup lint fmt test serve capture events

setup:   ## venv with base + dev deps (no heavy extras)
	uv venv
	uv pip install -e '.[dev]'

lint:    ## ruff lint + format check
	uv run --no-sync ruff check .
	uv run --no-sync ruff format --check .

fmt:     ## auto-fix + format
	uv run --no-sync ruff check --fix .
	uv run --no-sync ruff format .

test:    ## run tests
	uv run --no-sync pytest

serve:   ## serve the static viz at http://localhost:8000
	uv run --no-sync kvlens serve

capture: ## regenerate web/run.json (needs the vLLM simulate-forward build; see README)
	uv run --no-sync kvlens capture

events:  ## regenerate web/kv_events.json (needs the vLLM simulate-forward build; see README)
	uv run --no-sync kvlens events
