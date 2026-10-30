# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MANARA_STATE_DIR=/state \
    MANARA_PUBLISH_DIR=/published

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && (apt-get install -y --no-install-recommends tippecanoe || true) && rm -rf /var/lib/apt/lists/*

# Install dependencies first for Docker layer caching
COPY pipeline/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline scripts
COPY pipeline/ /app/

VOLUME ["/state", "/published"]

CMD ["python", "run.py", "schedule"]
