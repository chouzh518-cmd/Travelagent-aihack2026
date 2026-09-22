FROM python:3.12-slim

## Hugging Face Docker Spaces exposes port 7860 by default; Render overrides PORT.
ENV PYTHONUNBUFFERED=1 \
    APP_BIND_HOST=0.0.0.0 \
    APP_DATA_DIR=/var/data \
    PORT=7860

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /var/data

EXPOSE 7860
CMD ["python", "app.py"]
