FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV SIMULOOM_WORKSPACE=/app/workspace
EXPOSE 8000
CMD ["uvicorn", "simuloom.main:app", "--host", "0.0.0.0", "--port", "8000"]

