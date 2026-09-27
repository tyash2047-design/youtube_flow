FROM python:3.11-slim

# Install system dependencies: FFmpeg, git, media libraries, and nodejs for yt-dlp JS challenges
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    ca-certificates \
    curl \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install (ensure pip and yt-dlp are updated)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Ensure data directories exist
RUN mkdir -p data/downloads data/rendered

# Expose default port in case deployed as a Web Service
ENV PORT=10000
EXPOSE 10000

# Start command (handles both Web Service health check and Background Worker)
CMD ["python", "web_runner.py"]
