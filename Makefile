.PHONY: setup build dev demo doctor provision test smoke

setup:
	uv sync --python 3.12
	npm --prefix web ci
	$(MAKE) build

build:
	npm --prefix web run build

dev:
	.venv/bin/python -m uvicorn atp.main:app --host 127.0.0.1 --port 8000 --reload --no-access-log

demo:
	PYTHONPATH=. .venv/bin/python scripts/demo.py

doctor:
	PYTHONPATH=. .venv/bin/python scripts/manage.py doctor

provision:
	PYTHONPATH=. .venv/bin/python scripts/manage.py provision

test:
	.venv/bin/ruff check atp scripts tests
	.venv/bin/python -m pytest -q
	$(MAKE) build

smoke:
	PYTHONPATH=. .venv/bin/python scripts/smoke_audio.py
