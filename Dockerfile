FROM python:3.11-slim

ARG EBASE_VERSION=development
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="E-base Computer" \
      org.opencontainers.image.source="https://github.com/AAAmirinu/e-base-computer" \
      org.opencontainers.image.version="${EBASE_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md CHANGELOG.md LICENSE NOTICE TRADEMARKS.md TECHNICAL_SCOPE.md MANIFEST.in ./
COPY src ./src
COPY examples ./examples
COPY web ./web

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir .

EXPOSE 8765

CMD ["ebase-playground", "--host", "0.0.0.0", "--port", "8765"]
