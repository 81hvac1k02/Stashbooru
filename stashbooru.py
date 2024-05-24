import time

import aiohttp
import asyncio
import json
import base64
import stashapi.log as log
from stashapi.stashapp import StashInterface


class ServerInfo:
    deepbooru_domain = "deepbooru"
    stash_domain = "stash"
    stash_port_nr = 9999
    deepbooru_port_nr = 7860
    DEEPBOORU_URL = f"http://{deepbooru_domain}:{deepbooru_port_nr}/api/predict"  # replace with your API URL
    stash_api_key = ""
    stashargs = {
        "scheme": "http",
        "host": stash_domain,
        "port": stash_port_nr,
        "logger": log,
        "ApiKey": stash_api_key
    }
    stash = StashInterface(stashargs)


def get_untagged_images(return_amount=5) -> list:

    less_than_amount = 3
    page_nr = 2

    tag_count = {'tag_count': {'modifier': "LESS_THAN", 'value': less_than_amount}}

    query = {
        "per_page": return_amount,
        "sort": "created_at",
        "direction": "ASC",
        "page": page_nr
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


def get_existing_tag_ids(image_id: int) -> list[str]:
    current_ids = ServerInfo.stash.find_image(image_in=image_id, fragment='tags{id}')
    existing_tags = [dicts.get('id') for dicts in current_ids['tags']]
    return existing_tags


async def strip_tags(in_tags: tuple, image_id: int) -> list[int] | None:
    if len(in_tags) != 0:
        old_tag_ids = set(map(int, get_existing_tag_ids(image_id)))

        new_tags = [z.strip() for x in in_tags for z in x.split(',')]

        new_tag_ids = set(map(int, ServerInfo.stash.map_tag_ids(tags_input=new_tags, create=False)))

        if old_tag_ids == new_tag_ids:
            return None
        else:
            return list(old_tag_ids | new_tag_ids)
    return None


async def encode_image(image_id: int) -> str:
    image_url = f"http://{ServerInfo.stash_domain}:{ServerInfo.stash_port_nr}/image/{image_id}/thumbnail?apikey={ServerInfo.stash_api_key}"
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url) as response:
            if response.status == 200:
                image_content = await response.read()
                image_base64 = base64.b64encode(image_content)
                image_base64_string = image_base64.decode('utf-8')
                return image_base64_string


async def update_image_tags(*args, image_id: int) -> None:
    tag_ids = await strip_tags(args, image_id)

    if tag_ids is not None:
        try:
            log.info(f"updating image: {image_id}")
            ServerInfo.stash.update_image({'id': image_id, 'tag_ids': tag_ids})
        except Exception as update_err:
            print(f'Error occurred with image: {image_id}: {update_err}')


async def post_request(image_id: int, threshold=0.6) -> None:
    image = await encode_image(image_id)
    data = {
        "data": [image, threshold]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
                ServerInfo.DEEPBOORU_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(data)
        ) as response:
            try:
                response_json = await response.json()
                if 'data' in response_json:
                    response_data = response_json['data'][2]

                    await update_image_tags(response_data, image_id=image_id)

            except Exception as response_err:
                print(f'Error occurred: {response_err}')


async def handle_multiple_image_ids(image_ids: list) -> tuple:
    tasks = [post_request(image_id) for image_id in image_ids]
    results = await asyncio.gather(*tasks)
    return results


def main(minutes=10):
    # the script updates about 100 images per minute
    # the minute variable defines the execution time
    
    for m in range(minutes):
        image_ids = get_untagged_images(100)

        asyncio.run(handle_multiple_image_ids(image_ids))


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
