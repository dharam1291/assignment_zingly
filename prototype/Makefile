# Zingly prototype. Python 3.11+.
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
RUN     := .run
LIBS    := core channel ai_router agents auth policy saved_copy mcp handover
EDITABLE := $(foreach l,$(LIBS),-e libs/$(l)) -e services/voice_agent -e sims

.PHONY: install test run stop demo demo-handover demo-nordica chat spike clean

install:            ## venv + every library installed editable, like separate packages
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q $(EDITABLE) pytest

test:               ## unit tests per library + service integration + architecture rules
	$(BIN)/python -m pytest

run: stop           ## start mock PSS (:9001) and the voice agent (:8080) in the background
	@mkdir -p $(RUN)
	@$(BIN)/uvicorn mock_pss.app:app --port 9001 --log-level warning > $(RUN)/pss.log 2>&1 & echo $$! > $(RUN)/pss.pid
	@$(BIN)/uvicorn voice_agent.app:app --port 8080 --log-level warning > $(RUN)/voice_agent.log 2>&1 & echo $$! > $(RUN)/voice_agent.pid
	@for i in $$(seq 1 40); do curl -sf localhost:8080/health >/dev/null && curl -sf localhost:9001/stats >/dev/null && break; sleep 0.25; done
	@echo "mock PSS on :9001, voice agent on :8080 (logs in $(RUN)/)"

stop:
	@for f in $(RUN)/*.pid; do [ -f $$f ] && kill $$(cat $$f) 2>/dev/null; rm -f $$f; done; true

demo:               ## scripted happy path: likely -> verified -> side question -> rebooked
	$(BIN)/python -m genesys_sim --caller +447700900001 --say yes --say "Hi, my flight was cancelled" \
	  --say "A B C 1 2 3" --say "it's Smith" --say "where is my bag?" --say "the first one" --say yes --say "no thanks"

demo-handover:      ## PSS failing: the rebook fails safely and Genesys gets the screen-pop
	@curl -s -XPOST localhost:9001/admin/reset >/dev/null
	@curl -s -XPOST localhost:9001/admin/mode -H 'content-type: application/json' -d '{"airline":"atlantica","error_rate":1.0}' >/dev/null
	-$(BIN)/python -m genesys_sim --caller +15550001112 --queue-wait 300 --json --say yes \
	  --say "my booking ABC123 was cancelled" --say Smith --say second --say yes
	@curl -s -XPOST localhost:9001/admin/mode -H 'content-type: application/json' -d '{"airline":"atlantica","error_rate":0}' >/dev/null

demo-nordica:       ## same deployment, second tenant: different welcome, no consent prompt
	$(BIN)/python -m genesys_sim --dialed +4780001234 --caller +4791000001 --say "what's the status of NR456" --say "no thanks"

chat:               ## interactive call (type as the caller)
	$(BIN)/python -m genesys_sim --dialed +448000001234 --caller +447700900001

spike:              ## load test: unprotected vs protected against the 5 req/s PSS
	$(BIN)/python scripts/spike.py --mode compare

clean: stop
	rm -rf $(VENV) $(RUN) .pytest_cache
	find . -name __pycache__ -o -name '*.egg-info' | xargs rm -rf
