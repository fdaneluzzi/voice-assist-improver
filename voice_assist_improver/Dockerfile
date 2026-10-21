FROM python:3.13-alpine

# The app source is copied here by scripts/sync_addon.py (a Docker build only sees this folder).
COPY app /app
RUN pip install --no-cache-dir /app && rm -rf /app

WORKDIR /data
CMD ["python", "-m", "voice_assist_improver"]
