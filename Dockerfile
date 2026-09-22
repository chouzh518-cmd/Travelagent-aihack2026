FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    APP_BIND_HOST=0.0.0.0 \
    APP_DATA_DIR=/var/data \
    PORT=10000

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libgl1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /var/data

EXPOSE 10000
CMD ["python", "app.py"]
