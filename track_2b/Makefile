.PHONY: run stop logs clean

# Hack Apertus Track 2B — make run must start the project in Docker from a clean checkout.
# The server listens on 8000. LLM_NAME / LLM_BASE_URL / LLM_API_KEY are optional:
# when LLM_BASE_URL is unset the app runs in offline demo mode (still end-to-end).

IMAGE ?= hackapertus-track2b-light
PORT ?= 8000
CONTAINER ?= track2b-app

run:
	docker build -q -t $(IMAGE) .
	docker run -d --rm --name $(CONTAINER) -p 127.0.0.1:$(PORT):8000 \
	  -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY $(IMAGE)
	@for attempt in 1 2 3 4 5 6 7 8 9 10; do \
	  if docker exec $(CONTAINER) python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).read()" >/dev/null 2>&1; then exit 0; fi; \
	  sleep 1; \
	done; echo "Service did not become ready"; exit 1
	@echo "First Reply: http://localhost:$(PORT)/ui  (human approval required)"

stop:
	docker stop $(CONTAINER) 2>/dev/null || true

logs:
	docker logs -f $(CONTAINER)

clean:
	docker rmi $(IMAGE) 2>/dev/null || true
