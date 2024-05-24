FROM python:alpine 

RUN apk update 

RUN pip install stashapp-tools aiohttp asyncio python-dotenv

WORKDIR /opt/app

COPY . .

ENTRYPOINT ["python", "stashbooru.py"]
