FROM python:3.12-slim
WORKDIR /app
COPY src/ ./src/
COPY data/ ./data/
EXPOSE 8000
# stdlib only — no pip install, build works air-gapped once base image is present
CMD ["python", "src/server.py"]
