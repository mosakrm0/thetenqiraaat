FROM python:3.13-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY quran.db ./
COPY templates ./templates
COPY static ./static

EXPOSE 7860

CMD ["python", "-c", "from app import app, init_db; init_db(); app.run(host='0.0.0.0', port=7860)"]
