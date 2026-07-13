.PHONY: setup lint fmt test serve capture events

setup:   ## install dev deps into a uv-managed venv
	uv sync --extra dev

lint:    ## ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

fmt:     ## auto-fix + format
	uv run ruff check --fix .
	uv run ruff format .

test:    ## run tests
	uv run pytest

serve:   ## serve the static viz at http://localhost:8000
	uv run kvlens serve

capture: ## regenerate web/run.json (needs the vLLM simulate-forward build)
	uv run --extra capture kvlens capture

events:  ## regenerate web/kv_events.json (needs the vLLM simulate-forward build)
	uv run --extra capture kvlens events
