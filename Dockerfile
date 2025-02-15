FROM python:alpine 

RUN apk update && apk add --no-cache ffmpeg

WORKDIR /opt/app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "stashbooru.py"]
