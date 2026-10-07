FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*
COPY src/light_harness.py src/light_server.py src/llm_client.py src/light_skill.md src/source_reader.py src/company_import.py ./src/
COPY src/ui/light.html ./src/ui/light.html
COPY data/light-demo/ ./data/light-demo/
EXPOSE 8000
# Python stdlib only; prebuild this image for air-gapped deployment (local OCR).
CMD ["python", "src/light_server.py"]
