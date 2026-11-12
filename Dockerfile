FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# build tools are needed to compile TgCrypto
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# run as an unprivileged user; sessions/ and logs/ are writable (and used as named volumes)
RUN useradd -m -u 1000 botuser \
    && mkdir -p /app/sessions /app/logs \
    && chown -R botuser:botuser /app
USER botuser

CMD ["python", "bot.py"]
