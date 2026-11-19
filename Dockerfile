# Basisimage per Digest gepinnt (Dependabot hält ihn aktuell, siehe .github/dependabot.yml)
FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin fitpath \
 && mkdir /data && chown fitpath /data
COPY seed ./seed
COPY app ./app

USER fitpath
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
