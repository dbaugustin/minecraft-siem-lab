FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 5000
# 0.0.0.0 here is inside the container's own network namespace. Host exposure
# is controlled by the compose port mapping, which binds to 127.0.0.1 only.
# One worker process (with threads) because login lockout state is kept in
# memory: with several workers each would count failures separately.
# --timeout 300: stopping a world waits up to 60s for it to save, and the first
# start of a world may pull the itzg image, both well past gunicorn's 30s default.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "300", "app:app"]
