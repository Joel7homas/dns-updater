# Dockerfile for dns-updater v2.0.0

ARG VERSION=2.0.4

FROM python:3.12-alpine


WORKDIR /app

# Copy requirements first to leverage caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py \
     logger.py \
     api_client.py \
     dns_manager.py \
     container_monitor.py \
     cache_manager.py \
     api_client_core.py \
     api_client_requests.py \
     api_client_alt.py \
     ./

# Set default environment variables
ENV LOG_LEVEL=INFO \
    API_TIMEOUT=10 \
    API_RETRY_COUNT=3 \
    API_BACKOFF_FACTOR=0.3 \
    DNS_CACHE_TTL=60 \
    HEALTH_CHECK_INTERVAL=300 \
    VERSION=${VERSION}

LABEL version=${VERSION}
LABEL description="DNS updater with improved OPNsense compatibility"
LABEL maintainer="Joel Thomas"

CMD ["python", "main.py"]

