# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app/ /app/app/
COPY backend/migrations/ /app/migrations/

# Create unprivileged manara user and group for container security
RUN groupadd -g 10001 manara \
    && useradd -u 10001 -g manara -d /home/manara -m manara \
    && chown -R manara:manara /app /home/manara

USER manara

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010", "--proxy-headers", "--forwarded-allow-ips=*"]
