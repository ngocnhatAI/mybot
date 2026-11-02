FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MYBOT_DATA_DIR=/app/data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mybot ./mybot
COPY config.yaml .

CMD ["python", "-m", "mybot", "run"]
