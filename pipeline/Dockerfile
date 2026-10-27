# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MANARA_STATE_DIR=/state \
    MANARA_PUBLISH_DIR=/published

WORKDIR /app

# Install dependencies first for Docker layer caching
COPY pipeline/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline scripts
COPY pipeline/ /app/

VOLUME ["/state", "/published"]

CMD ["python", "run.py", "schedule"]
