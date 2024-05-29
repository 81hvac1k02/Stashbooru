import asyncio
import base64
import json

import aiohttp

from stashbooru import ServerInfo, error_log


def get_untagged_images(return_amount=5, page_nr=1) -> list:
    less_than_amount = 3

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
        }  # avif currently fails to get parsed by deepbooru
    }

    images = ServerInfo.stash.find_images(filter=query, f=tag_is_null, fragment='id')

    if not images:  # testing if the returned amount is empty
        page_nr = page_nr + 5
        query['page'] = page_nr
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

        if old_tag_ids == new_tag_ids or len(old_tag_ids) > len(new_tag_ids):  # if the preexisting tags are equal to the ones from deepbooru or there's more tags, skip
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
            ServerInfo.stash.log.info(f"updating image: {image_id}")
            ServerInfo.stash.update_image({'id': image_id, 'tag_ids': tag_ids})
        except Exception as update_err:
            error_log(update_err)


async def post_request(image_id: int, threshold=0.7) -> None:
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
                error_log(response_err)


async def handle_multiple_image_ids(image_ids: list) -> tuple:
    tasks = [post_request(image_id) for image_id in image_ids]
    results = await asyncio.gather(*tasks)
    return results


def run(minutes=10) -> None:
    # the script updates about 100 images per minute
    # the minute variable defines the execution time
    for m in range(minutes):
        # image_ids = get_untagged_images(return_amount=100, page_nr=7)
        image_ids = get_untagged_images(return_amount=-1, page_nr=1)
        asyncio.run(handle_multiple_image_ids(image_ids))
