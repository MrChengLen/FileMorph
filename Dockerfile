FROM python:3.12-slim

# Install system dependencies (ffmpeg, libheif, rendering libs for WeasyPrint)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      libheif-dev \
      libffi-dev \
      libssl-dev \
      build-essential \
      pango1.0-tools \
      libcairo2 \
      libpangocairo-1.0-0 \
      libgdk-pixbuf-xlib-2.0-0 \
      curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Ensure data directory exists and entrypoint is executable
# sed removes Windows CRLF line endings in case the file was edited on Windows
RUN mkdir -p data && \
    sed -i 's/\r$//' entrypoint.sh && \
    chmod +x entrypoint.sh

# Security: run as non-root user (principle of least privilege — PT-012)
RUN groupadd --system appuser && useradd --system --gid appuser appuser && \
    chown -R appuser:appuser /app && \
    mkdir -p /app/data && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
