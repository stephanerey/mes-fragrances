FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app

RUN pip install --upgrade pip \
    && pip install .

RUN mkdir -p /data/feeds /data/reports /data/logs

VOLUME ["/data"]

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["--help"]
