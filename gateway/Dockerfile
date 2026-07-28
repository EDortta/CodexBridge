FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY gateway /app/gateway
COPY shared /app/shared
COPY examples /app/examples

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["uvicorn", "gateway.app.main:app", "--host", "0.0.0.0", "--port", "8080"]

