# Évaluateur d'offres Jev — image auto-portante.
# Aucune dépendance externe : le moteur de CV et ses polices sont embarqués dans engine/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    JEV_CONFIG=/config/config.toml

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Sources, moteur de CV embarqué (polices incluses), profil et configuration d'exemple
COPY app ./app
COPY engine ./engine
COPY scripts ./scripts
COPY PROFILE.json config.example.toml ./

# utilisateur non privilégié par défaut ; docker-compose peut le remplacer par ton uid
RUN mkdir -p /data /config && useradd -m -u 10001 jev && chown -R jev:jev /data /config /app
USER jev

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"

# serve.py lit config.toml puis démarre uvicorn (HOST/PORT surchargeables)
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "8000"]
