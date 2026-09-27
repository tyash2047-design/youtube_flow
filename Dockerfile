FROM python:3.11-slim

# Install system dependencies: FFmpeg, git, and media libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Ensure data directories exist
RUN mkdir -p data/downloads data/rendered

# Expose default port in case deployed as a Web Service
ENV PORT=10000
EXPOSE 10000

# Start command (handles both Web Service health check and Background Worker)
CMD ["python", "web_runner.py"]
