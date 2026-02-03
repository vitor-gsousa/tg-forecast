FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y tzdata && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Lisbon

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY forecast.py .
COPY images/ ./images/

CMD ["python", "forecast.py"]