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

EXPOSE 6000

CMD ["python", "-c", "from app import init_db; init_db(); import os; os.system('gunicorn -w 4 -b 0.0.0.0:6000 app:app')"]
