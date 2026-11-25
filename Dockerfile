FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ENV PORT=7860

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py db.py app.py seed_db.py ./
COPY services ./services
COPY data ./data
COPY quran.db ./
COPY templates ./templates
COPY static ./static

RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && mkdir -p /app/.cache \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/imams', timeout=3)" || exit 1

CMD ["sh", "-c", "python -c 'from app import init_db; init_db()' && exec gunicorn -w 4 --threads 2 --timeout 60 -b 0.0.0.0:${PORT:-7860} app:app"]
