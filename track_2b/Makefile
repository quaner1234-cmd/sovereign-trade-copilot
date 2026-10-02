.PHONY: run stop logs clean

# Hack Apertus Track 2B — make run must start the project in Docker from a clean checkout.
# The server listens on 8000. LLM_NAME / LLM_BASE_URL / LLM_API_KEY are optional:
# when LLM_BASE_URL is unset the app runs in offline demo mode (still end-to-end).

IMAGE ?= hackapertus-track2b
PORT  ?= 8000

run:
	docker build -q -t $(IMAGE) .
	docker run -d --rm --name track2b-app -p $(PORT):8000 \
	  -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY $(IMAGE)
	@echo "track2b up: http://localhost:$(PORT)/health  (POST /process)"

stop:
	docker stop track2b-app 2>/dev/null || true

logs:
	docker logs -f track2b-app

clean:
	docker rmi $(IMAGE) 2>/dev/null || true
