# syntax=docker/dockerfile:1
FROM buildpack-deps:bookworm AS tippecanoe-builder

RUN git clone --depth 1 https://github.com/felt/tippecanoe.git /tmp/tippecanoe \
    && cd /tmp/tippecanoe \
    && make -j$(nproc) \
    && make install

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    MANARA_STATE_DIR=/state \
    MANARA_PUBLISH_DIR=/published

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=tippecanoe-builder /usr/local/bin/tippecanoe /usr/local/bin/tippecanoe
COPY --from=tippecanoe-builder /usr/local/bin/tile-join /usr/local/bin/tile-join

# Install dependencies first for Docker layer caching
COPY pipeline/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline scripts
COPY pipeline/ /app/
COPY content/ /app/content/

# Create unprivileged manara user and group for container security
RUN groupadd -g 10001 manara \
    && useradd -u 10001 -g manara -d /home/manara -m manara \
    && mkdir -p /state /published /home/manara \
    && chown -R manara:manara /app /state /published /home/manara \
    && chmod +x /app/docker-entrypoint.sh

VOLUME ["/state", "/published"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "run.py", "schedule"]
