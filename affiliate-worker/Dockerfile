FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN mkdir -p /data/feeds /data/reports /data/logs

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "app.main"]
