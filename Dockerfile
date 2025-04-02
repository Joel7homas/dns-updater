# Dockerfile
FROM python:3.12-alpine

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dns_updater.py .

LABEL version="1.0.4"

CMD ["python", "dns_updater.py"]


