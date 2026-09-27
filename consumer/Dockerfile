FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Create non-root user
RUN useradd -m -u 1001 consumer && chown -R consumer:consumer /app
USER consumer

# Expose metrics port
EXPOSE 9091

# Run the consumer with unbuffered output for immediate logging
CMD ["python", "-u", "-m", "src.main"]