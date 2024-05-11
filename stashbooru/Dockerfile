FROM python:alpine 


RUN apk update 

RUN pip install stashapp-tools aiohttp asyncio 

WORKDIR /opt/app

COPY . .

ENTRYPOINT ["python", "stashbooru.py"]
