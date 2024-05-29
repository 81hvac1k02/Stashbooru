FROM python:alpine 

RUN apk update 

WORKDIR /opt/app

COPY . .

RUN pip install -r requirements.txt

ENTRYPOINT ["python", "stashbooru.py"]
