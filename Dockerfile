FROM python:3.10-alpine

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

# Store the Pyrogram session under /data so it can be mounted as a volume
# and survive container recreation (avoids creating a new auth key on restart).
ENV SESSION_DIR=/data
RUN mkdir -p /data

CMD ["python", "main.py"]
