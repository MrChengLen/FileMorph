# ----------------------------------------------------------------------------
# Stage 1 — base image (filemorph:latest)
# ----------------------------------------------------------------------------
# Pure-Python conversion stack: ffmpeg + libheif for media, Cairo / Pango
# for WeasyPrint, Ghostscript for the PDF/A-2b re-render path. Self-hosters
# who only convert images, audio, video, markdown, or txt — and who accept
# the mammoth+WeasyPrint fidelity ceiling for docx→pdf — pull this tag.
FROM python:3.12-slim AS base

# Install system dependencies:
# - ffmpeg, libheif, cairo/pango: media + WeasyPrint rendering
# - ghostscript: PDF/A-2b re-render path (app/converters/_ghostscript.py).
#   Optional at runtime — pdfa.py falls back to markup-only when gs is
#   missing — but bundling it here ensures the upgrade path is on by
#   default for self-hosters of the official image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      ghostscript \
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


# ----------------------------------------------------------------------------
# Stage 2 — office variant (filemorph:office)
# ----------------------------------------------------------------------------
# Adds LibreOffice headless + OFL metric-compatible fonts on top of the
# base image. Self-hosters who need Word-grade docx→pdf fidelity
# (footnotes, headers/footers, TOC, multi-section layout, multi-level
# numbered lists, equations, OLE) pull this tag. ~280 MB larger than the
# slim base. With FILEMORPH_OFFICE_ENGINE=auto (default), simple DOCX
# still routes through the fast mammoth pipeline; only docs with
# complex features delegate to LibreOffice.
#
# Font choice rationale:
#   - fonts-crosextra-carlito: OFL Calibri-metric — the default font in
#     every modern Word doc; rendering the document in Calibri-metric
#     Carlito preserves line breaks and pagination identically to Word.
#   - fonts-liberation: OFL Arial/Times/Courier-metric — the second most
#     common font family in Behörden / Kanzlei letterheads.
#   - fonts-dejavu-core: broad-coverage Latin / Greek / Cyrillic fallback
#     so Verwaltungsvorlagen with mixed language inserts don't reflow into
#     tofu.
# Microsoft's actual Calibri / Arial / Times are not redistributable; the
# metric-compat substitutes are the standard open-source path also taken
# by Stirling-PDF and the Collabora / Nextcloud Office stacks.
FROM base AS office
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      libreoffice-core \
      libreoffice-writer \
      fonts-crosextra-carlito \
      fonts-liberation \
      fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*
USER appuser
