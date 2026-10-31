# MELBCUP web app (FastAPI) for Azure Container Apps. Render (render.yaml) stays as the backup host.
# Build: docker build -t melbcup-web .   Run: docker run -p 8000:8000 -e APP_PASSWORD=x melbcup-web
# Secrets (FORMFAV_API_KEY, APP_PASSWORD) are injected at run time, never baked in.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PRICE_MODE=manual

WORKDIR /app

# Only what `pip install .` needs, so a docs or research change does not rebuild the layer.
COPY pyproject.toml ./
COPY melbcup ./melbcup
RUN pip install --no-cache-dir .

RUN useradd --system --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "melbcup.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
