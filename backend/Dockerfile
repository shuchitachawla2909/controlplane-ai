FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY pytest.ini ./pytest.ini

# Data dir for the SQLite file (mounted as a volume in docker-compose)
RUN mkdir -p /data
ENV CONTROLPLANE_DB_URL=sqlite:////data/controlplane.db \
    CONTROLPLANE_CONFIG_DIR=/config

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
