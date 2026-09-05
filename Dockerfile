FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y tzdata && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=Europe/Lisbon

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY modules/ ./modules/
COPY web/ ./web/
COPY images/ ./images/

EXPOSE 8080

CMD ["python", "main.py"]