FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Create persistent data directory
RUN mkdir -p /data

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/workflows.db
ENV LOCAL_WORKFLOWS_DIR=""
ENV ADMIN_USER=admin
ENV ADMIN_PASS=changeme
ENV SECRET_KEY=change-this-to-random-string
ENV INITIAL_REPOS=https://github.com/DragonJAR/n8n-workflows-esp/tree/main/workflows
ENV GITHUB_TOKEN=""
ENV SYNC_INTERVAL_HOURS=24
ENV GEMINI_API_KEY=""
ENV GEMINI_MODEL=models/gemini-flash-latest

EXPOSE 8000

VOLUME /data

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
