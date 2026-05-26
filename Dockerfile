# ----------------------------------------------------------------------------
# Stage 1 — builder (compilers + dev headers; never shipped)
# ----------------------------------------------------------------------------
# Some Python wheels need to compile C extensions at install time if no
# prebuilt manylinux wheel matches the target platform — most commonly
# ``pillow-heif`` on ARM hosts, ``cryptography`` on older glibc builds,
# and anything that uses ``cffi``. Pinning the compile toolchain to a
# throwaway stage means the final image never ships ``build-essential``,
# ``libheif-dev``, ``libffi-dev`` or ``libssl-dev`` — saving ~250-300 MB
# of installed size and removing the corresponding attack surface (no
# gcc / ld / make on the running container, no header tree for an
# attacker who lands inside the FS to probe against).
#
# The installed Python tree lives in ``/opt/venv`` so the runtime stage
# can ``COPY --from=builder /opt/venv /opt/venv`` in one shot rather than
# fishing site-packages out of the system Python prefix.
# Pinned to python:3.12-slim (tag kept here for human readability; digest is the
# enforcement). Comment moved off the FROM line because newer BuildKit parsers
# count trailing comments as a fourth argument and reject the directive with
# "FROM requires either one or three arguments".
FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libheif-dev \
      libffi-dev \
      libssl-dev && \
    rm -rf /var/lib/apt/lists/*

# Dedicated venv so the runtime COPY is one directory tree (vs.
# ``/usr/local/lib/python3.12/site-packages`` mixed with system files).
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Layer-cache friendly: requirements first, then the rest. A
# ``requirements.txt`` edit invalidates this layer; an application-code
# edit does not (the COPY . . in the runtime stage is a separate layer).
COPY requirements.txt .
RUN pip install -r requirements.txt


# ----------------------------------------------------------------------------
# Stage 2 — base image (filemorph:latest) — runtime libs only
# ----------------------------------------------------------------------------
# Pure-Python conversion stack: ffmpeg + libheif for media, Cairo / Pango
# for WeasyPrint, Ghostscript for the PDF/A-2b re-render path. Self-hosters
# who only convert images, audio, video, markdown, or txt — and who accept
# the mammoth+WeasyPrint fidelity ceiling for docx→pdf — pull this tag.
#
# Runtime-only apt set (no ``*-dev`` headers, no ``build-essential``):
#   - ffmpeg: audio/video conversion + compression
#   - ghostscript: PDF/A-2b re-render path (``app/converters/_ghostscript.py``);
#     pdfa.py falls back to markup-only when gs is missing, but we ship it
#     so the upgrade path is on by default.
#   - libheif1: runtime decoder ``pillow-heif`` dlopens at register-opener
#     time. Without it, ``register_heif_opener()`` fails gracefully and
#     HEIC inputs return 422 — degraded but not crashed.
#   - libcairo2 / libpangocairo-1.0-0 / libgdk-pixbuf-xlib-2.0-0 /
#     pango1.0-tools: WeasyPrint native dependency tree.
#   - curl: in-container ``HEALTHCHECK`` driver (compose.yml uses
#     ``curl -f http://localhost:8000/api/v1/health``).
# ``libssl3`` and ``libffi8`` are already present in python:3.12-slim
# (Python's _ssl + cffi need them) so we don't reinstall them here.
# Pinned to python:3.12-slim (same image as builder; digest is the enforcement).
FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS base

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      ghostscript \
      libheif1 \
      libcairo2 \
      libpangocairo-1.0-0 \
      libgdk-pixbuf-xlib-2.0-0 \
      pango1.0-tools \
      curl && \
    rm -rf /var/lib/apt/lists/*

# Bring in the compiled Python tree from the builder stage. The venv's
# shebangs already point at ``/opt/venv/bin/python``; activating it via
# PATH means ``python``, ``pip``, ``uvicorn``, ``alembic``, etc. resolve
# to the venv binaries.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Copy application code (separate layer from requirements so app edits
# don't invalidate the builder's pip-install layer).
COPY . .

# Ensure data directory exists and entrypoint is executable.
# sed removes Windows CRLF line endings in case the file was edited on Windows.
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
# Stage 3 — office variant (filemorph:office)
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
