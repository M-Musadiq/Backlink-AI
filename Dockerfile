FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for browser-use / playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Set Python path
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.presentation.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
