# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 ddhelper
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pyproject.toml README.md LICENSE THIRD_PARTY_LICENSES.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-deps . && mkdir -p /app/data && chown ddhelper:ddhelper /app/data

USER ddhelper
VOLUME ["/app/data"]
# Configure via --env-file .env (never bake secrets into the image).
ENTRYPOINT ["python", "-m", "ddhelper"]
CMD ["run"]
