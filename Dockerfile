# Minimal Dockerfile for OpenMontage service image
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Install build deps for common Python packages; keep image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps if requirements.txt exists
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt || true

# Copy repository
COPY . /app

# Default command: open a shell. Replace with your service entrypoint when ready.
CMD ["/bin/bash"]
