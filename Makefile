.PHONY: dev server client test venv

dev: venv
	. venv/bin/activate && pip install -r requirements.txt

server:
	. venv/bin/activate && export LEGAL_DOC_ROOT=./data && python -u mcp_server/server.py

client:
	. venv/bin/activate && python -u client/agent_cli.py "$(q)"

test:
	. venv/bin/activate && pytest -q

venv:
	python3 -m venv venv

api:
	. venv/bin/activate && pip install -r requirements.txt && uvicorn web_server.api:app --reload --port 8000

web-install:
	npm --prefix web install

web-dev:
	npm --prefix web run dev
