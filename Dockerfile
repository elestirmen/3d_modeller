FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app.py catalog.py categories.py meshes.py ./
COPY static/ ./static/
COPY templates/ ./templates/

EXPOSE 5000

# Tek süreç + çok iş parçacığı: yükleme oturumları, giriş denemesi sayacı ve
# arka plan kuyruğu süreç içinde tutulur. Ağır render işleri ayrı alt süreçte çalışır.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "300", "--graceful-timeout", "30", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
