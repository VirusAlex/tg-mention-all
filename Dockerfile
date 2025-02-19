FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py ./

# By default, Pyrogram creates a session file in the folder where the script is running
# If you want, you can redirect to another path:
# ENV PYROGRAM_SESSION_DIR=/data
# RUN mkdir /data

CMD ["python", "main.py"]
