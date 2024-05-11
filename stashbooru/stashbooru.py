import time

import aiohttp
import asyncio
import json
import base64
import stashapi.log as log
from stashapi.stashapp import StashInterface


class ServerInfo:
    # server_url = "192.168.2.8"
    port_nr = 7860
    REALBOORU_API_URL = f"http://deepbooru:{port_nr}/api/predict"  # replace with your API URL
    api_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOiJTdGV2ZSIsInN1YiI6IkFQSUtleSIsImlhdCI6MTcxMjY2NzE2N30.Kutcw3YJhe2UAbNSoOuxkjnxPvaFb-I13aGUjHOMnw0"
    stashargs = {
        "scheme": "http",
        "host": "stash",
        "port": "9999",
        "logger": log,
        "ApiKey": api_key
    }
    stash = StashInterface(stashargs)


def get_untagged_images(return_amount=5) -> list:
    # return_amount = 5
    less_than_amount = 3

    tag_count = {'tag_count': {'modifier': "LESS_THAN", 'value': less_than_amount}}

    query = {
        "per_page": return_amount,
        "sort": "created_at",
        "direction": "ASC"
    }

    tag_is_null = {
        "tags": {
            "value": [],
            "excludes": [],
            "modifier": "IS_NULL",
            "depth": 0
        },
        "path": {
            "value": ".avif",
            "modifier": "EXCLUDES"
        }
    }  # avif currently fails to get parsed by deepbooru

    images = ServerInfo.stash.find_images(filter=query, f=tag_is_null, fragment='id')
    if not images:
        images = ServerInfo.stash.find_images(filter=query, f=tag_count, fragment='id')

    image_ids = [i.get('id') for i in images]
    return image_ids


def get_existing_tag_ids(image_id: int) -> list:
    existing_tags = []
    current_ids = ServerInfo.stash.find_image(image_in=image_id, fragment='tags{id}')
    for dicts in current_ids['tags']:
        existing_tags.append(dicts.get('id'))
    return existing_tags


def strip_tags(tags, image_id: int) -> list:
    if len(tags) != 0:
        old_tag_ids = get_existing_tag_ids(image_id)

        new_tags = [z.strip() for x in tags for z in x.split(',')]

        new_tag_ids = ServerInfo.stash.map_tag_ids(tags_input=new_tags, create=True)

        tag_ids = old_tag_ids + new_tag_ids

        return tag_ids
    return None


async def encode_image(image_id: int) -> str:
    image_url = f"http://stash:9999/image/{image_id}/thumbnail?apikey={ServerInfo.api_key}"
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status == 200:
                image_content = await response.read()
                image_base64 = base64.b64encode(image_content)
                image_base64_string = image_base64.decode('utf-8')
                return image_base64_string


async def update_image_tags(*args, image_id: int):
    tag_ids = strip_tags(args, image_id)
    if tag_ids is not None:
        try:
            log.info(f"updating image: {image_id}")
            ServerInfo.stash.update_image({'id': image_id, 'tag_ids': tag_ids})
        except Exception as err:
            print(f'Error occurred: {err}')


async def post_request(image_id: int, threshold=0.6):
    image = await encode_image(image_id)
    data = {
        "data": [image, threshold]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
                ServerInfo.REALBOORU_API_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(data)
        ) as response:
            response_json = await response.json()

            response_data = response_json['data'][2]

            update = await update_image_tags(response_data, image_id=image_id)

            # return response_json


async def handle_multiple_image_ids(image_ids: list) -> tuple:
    tasks = [post_request(image_id) for image_id in image_ids]
    results = await asyncio.gather(*tasks)
    return results


def main():
    # the script updates about 100 images per minute
    # the minute variable defines the execution time
    minutes = 1
    # for m in range(minutes):
    while (True):
        image_ids = get_untagged_images(100)
        # image_ids = [6348]
        test = asyncio.run(handle_multiple_image_ids(image_ids))


if __name__ == "__main__":
    start_time = time.time()
    try:
        main()
    except KeyboardInterrupt:
        print("execution interrupted by user")
    except Exception as err:
        print(f'Error occurred: {err}')
    end_time = time.time()
    exec_time = end_time - start_time
    print(f"it took {exec_time} seconds")
