FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

ENV PORT=7860

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY quran.db ./
COPY templates ./templates
COPY static ./static

EXPOSE 7860

CMD ["sh", "-c", "python -c 'from app import init_db; init_db()' && exec gunicorn -w 4 -b 0.0.0.0:${PORT:-7860} app:app"]
