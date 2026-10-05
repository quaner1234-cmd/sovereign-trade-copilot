FROM python:3.12-slim
WORKDIR /app
COPY src/light_harness.py src/light_server.py src/llm_client.py src/light_skill.md ./src/
COPY src/ui/light.html ./src/ui/light.html
COPY data/light-demo/ ./data/light-demo/
EXPOSE 8000
# stdlib only — no pip install, build works air-gapped once base image is present
CMD ["python", "src/light_server.py"]
