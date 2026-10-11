# Compta MA - image applicative (phase 1 SQLite et phase 2/3 PostgreSQL)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Les dependances sont copiees en premier pour profiter du cache Docker
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Utilisateur non privilegie (bonne pratique en production)
RUN useradd --create-home --shell /bin/bash compta \
    && chown -R compta:compta /app
USER compta

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]