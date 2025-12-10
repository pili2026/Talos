FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install minimal OS packages (timezone etc.)
RUN apt-get update && \
    apt-get install -y --no-install-recommends tzdata && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Ensure /tmp exists for logical serial ports like /tmp/ttyV0
RUN mkdir -p /tmp

# Make entrypoint executable
RUN chmod +x /app/docker_entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker_entrypoint.sh"]
