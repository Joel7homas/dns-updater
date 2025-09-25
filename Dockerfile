# Dockerfile for dns-updater v2.2.0 with distributed DNS

ARG VERSION=2.2.7

FROM python:3.12-alpine

# Install curl and CA certificates
RUN apk add --no-cache curl ca-certificates

WORKDIR /app

# Copy requirements first to leverage caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - INCLUDING NEW DISTRIBUTED DNS FILES
COPY main.py \
     logger.py \
     api_client.py \
     api_client_core.py \
     api_client_requests.py \
     api_client_alt.py \
     dns_manager.py \
     distributed_dns_manager.py \
     dns_replication_api.py \
     container_monitor.py \
     cache_manager.py \
     module_check.py \
     dns-mass-cleanup.py \
     container_network_state.py \
     ./

# Copy diagnostics directory if it exists
COPY diagnostics/ ./diagnostics/

# Set default environment variables
ENV LOG_LEVEL=INFO \
    API_TIMEOUT=10 \
    API_RETRY_COUNT=3 \
    API_BACKOFF_FACTOR=0.3 \
    DNS_CACHE_TTL=60 \
    HEALTH_CHECK_INTERVAL=300 \
    VERSION=${VERSION}

LABEL version=${VERSION}
LABEL description="DNS updater with distributed DNS support"
LABEL maintainer="Joel Thomas"

CMD ["python", "main.py"]
