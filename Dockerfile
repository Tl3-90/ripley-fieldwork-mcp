FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system --gid 10001 ripley \
    && useradd --system --uid 10001 --gid ripley --home-dir /app --no-create-home ripley

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app.py models.py ripley_auth.py ripley_client.py ./

USER ripley

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
