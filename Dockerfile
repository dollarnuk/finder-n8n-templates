FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create data directories
RUN mkdir -p /data /app/data/workflows

# Environment defaults
ENV DB_PATH=/data/workflows.db
ENV LOCAL_WORKFLOWS_DIR=/app/data/workflows
ENV ADMIN_USER=admin
ENV ADMIN_PASS=changeme
ENV SECRET_KEY=change-this-to-random-string
ENV INITIAL_REPOS=""
ENV GITHUB_TOKEN=""
ENV SYNC_INTERVAL_HOURS=24

EXPOSE 8000

VOLUME /data

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
