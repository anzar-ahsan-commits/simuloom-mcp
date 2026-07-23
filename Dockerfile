FROM python:3.14-slim

LABEL org.opencontainers.image.source="https://github.com/anzar-ahsan-commits/simuloom-mcp" \
      org.opencontainers.image.description="Contract-driven service virtualization and synthetic test-data control plane" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 simuloom \
    && mkdir -p /app/workspace \
    && chown -R simuloom:simuloom /app

ENV SIMULOOM_WORKSPACE=/app/workspace \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/readyz', timeout=2)"]
USER 10001:10001
ENTRYPOINT ["python", "-m", "simuloom.container_entrypoint"]
CMD ["uvicorn", "simuloom.main:app", "--host", "0.0.0.0", "--port", "8000"]
