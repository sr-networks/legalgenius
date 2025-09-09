.PHONY: dev server client test venv api web-install web-dev \
	gesetze-install gesetze-update-list gesetze-download gesetze-convert gesetze-all index-gesetze \
	es-up es-wait bootstrap-laws urteile-neuris index-urteile

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
	. venv/bin/activate && pip install -r requirements.txt && uvicorn web_server.api:app --reload --port 8000 --env-file .env

web-install:
	npm --prefix web install

web-dev:
	npm --prefix web run dev -- --host 0.0.0.0 --port 5173

# ---- Bundesgesetze scraping helpers ----

gesetze-install: venv
	. venv/bin/activate && pip install -r scrapers/gesetze-tools/requirements.txt

gesetze-update-list: gesetze-install
	. venv/bin/activate && cd scrapers/gesetze-tools && python lawde.py updatelist

gesetze-download: gesetze-install
	. venv/bin/activate && cd scrapers/gesetze-tools && python lawde.py loadall --path laws

gesetze-convert: gesetze-install
	. venv/bin/activate && cd scrapers/gesetze-tools && python lawdown.py convert laws ../../data/gesetze

gesetze-all: gesetze-install gesetze-update-list gesetze-download gesetze-convert

index-gesetze: venv
	. venv/bin/activate && python simple_elasticsearch_indexer.py --gesetze-only

# ---- Elasticsearch helpers ----

es-up:
	@echo "Starting Elasticsearch container (or creating if missing)..."
	@docker start elasticsearch-simple >/dev/null 2>&1 || docker run -d --name elasticsearch-simple \
	  -p 9200:9200 -p 9300:9300 \
	  -e "discovery.type=single-node" \
	  -e "xpack.security.enabled=false" \
	  -e "ES_JAVA_OPTS=-Xms512m -Xmx512m" \
	  elasticsearch:8.11.0

es-wait:
	@echo "Waiting for Elasticsearch to become ready..."
	@TRIES=0; \
	until curl -sSf http://localhost:9200 >/dev/null 2>&1; do \
	  TRIES=$$((TRIES+1)); \
	  if [ $$TRIES -gt 60 ]; then echo "Elasticsearch not responding after 60s"; exit 1; fi; \
	  sleep 1; \
	done; \
	echo "Elasticsearch is up."

# ---- One-shot bootstrap ----

bootstrap-laws: gesetze-all es-up es-wait index-gesetze
	@echo "Bootstrap complete: laws scraped, converted, and indexed."

urteils-years ?= 2000
urteils-years-to ?= $(shell date +%Y)

urteils-out ?= data/urteile_markdown_by_year

urteils-base ?= https://testphase.rechtsinformationen.bund.de
urteils-search ?= /v1/case-law
urteils-detail ?= /v1/case-law/{id}

urteils-collection ?= 

urteile-neuris: venv
	. venv/bin/activate && python scrapers/fetch_urteile_neuris.py \
	  --base-url $(urteils-base) \
	  --search-path $(urteils-search) \
	  --detail-path $(urteils-detail) \
	  --from-year $(urteils-years) \
	  --to-year $(urteils-years-to) \
	  --collection-value $(urteils-collection) \
	  --out $(urteils-out)
index-urteile: venv
	. venv/bin/activate && python simple_elasticsearch_indexer.py --urteile-only
