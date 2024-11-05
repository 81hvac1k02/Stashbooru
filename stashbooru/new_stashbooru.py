import asyncio
import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Literal, Optional, Union

import aiofiles
import stashapi.log as log
from aiohttp import ClientSession
from dotenv import dotenv_values, load_dotenv
from stashapi.stashapp import StashInterface


class ServerConfig:
    def __init__(self):
        if not load_dotenv():
            raise ValueError("no .env found")
        self.config = dotenv_values('.env')
        self.deepbooru_domain = self.config["deepbooru_domain"]
        self.stash_domain = self.config["stash_domain"]
        self.stash_api_key = self.config["stash_api_key"]
        self.deepbooru_port_nr = 7860
        self.stash_port_nr = 9999

    @property
    def deepbooru_url(self):
        return f"http://{self.deepbooru_domain}:{self.deepbooru_port_nr}/api/predict"

    @property
    def stash_args(self):
        return {
            "scheme": "http",
            "host": self.stash_domain,
            "port": self.stash_port_nr,
            "logger": log,
            "ApiKey": self.stash_api_key
        }


class ServerInfo:
    _config = ServerConfig()
    stash = StashInterface(_config.stash_args)

    deepbooru_url = _config.deepbooru_url

    stash_api_key = _config.stash_args['ApiKey']


def get_untagged_files(file_type: Literal["image", "scene"], return_amount=5, page_nr=1) -> Optional[list[dict[str, str | dict]]]:
    uri = {"image": "thumbnail", "scene": "preview"}
    fragment = f"id paths{{{uri[file_type]}}}"
    query = {
        "per_page": return_amount,
        "sort": "created_at",
        "direction": "ASC",
        "page": page_nr
    }
    tag_is_null = {
        'is_missing': "tags"}
    stash = ServerInfo.stash
    if file_type == "image":
        tag_is_null["path"] = {
            "value": ".avif",
            "modifier": "EXCLUDES"
        }  # avif currently fails to get parsed by deepbooru
        return stash.find_images(filter=query, fragment=fragment, image_filter=tag_is_null)
    elif file_type == "scene":
        tag_is_null['framerate'] = {
            "modifier": "GREATER_THAN",
            "value": 0
        }
        return stash.find_scenes(filter=query, fragment=fragment, scene_filter=tag_is_null)
    else:
        return None


async def process_video(input_file_path: str | Path) -> None:
    if isinstance(input_file_path, str):
        input_file_path = Path(input_file_path)

    output_pattern = f"{input_file_path.with_suffix('').as_posix()}_keyframe_%03d.png"

    # Adjust the command to use VAAPI
    command = (
        f"ffmpeg -loglevel warning -hwaccel vaapi -hwaccel_device /dev/dri/renderD128 "
        f"-i {input_file_path} "
        f"-vf 'select=eq(pict_type\\,PICT_TYPE_I),format=vaapi_vld' -fps_mode vfr "
        f"{output_pattern}"
    )

    await asyncio.to_thread(subprocess.run, command, shell=True, check=True)


async def collect_image_hashes(search_dir: str, file_id: str) -> Optional[set[str]]:
    file_hashes = set()

    for root, _, files in os.walk(search_dir):
        tasks = []
        for file in files:
            if file.endswith('.png') and file.startswith(file_id):
                path = os.path.join(root, file)
                tasks.append(encode_image(path))
        if tasks:
            file_hashes.update(await asyncio.gather(*tasks))  # Run all tasks concurrently
    return file_hashes or None


async def download_file(session: ClientSession, url: str) -> Optional[bytes]:
    async with session.get(url) as response:
        if response.status == 200:
            file_content = await response.read()
            return file_content
        else:
            raise Exception(f"Failed to download file: {response.status}")


async def encode_image(image_source: Union[str, bytes]) -> str:
    if isinstance(image_source, str):
        filepath = Path(image_source)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        # Asynchronously read the image file
        async with aiofiles.open(filepath, "rb") as f:
            image_content = await f.read()
    elif isinstance(image_source, bytes):
        image_content = image_source
    else:
        raise ValueError("image_source must be a file path string or bytes.")

    # Encode the image content to base64
    image_base64 = base64.b64encode(image_content)
    image_base64_string = image_base64.decode('utf-8')
    return image_base64_string


async def handle_tags(session: ClientSession, encoded_strings: Iterable[str]) -> set[str]:
    tags = set()
    for enc_str in encoded_strings:
        if tag_str := await post_request(enc_str, session):
            for tag in tag_str.split(','):
                tags.add(tag.strip())
    return tags


async def post_request(encoded_string: str, session: ClientSession, threshold: float = 0.6) -> Optional[str]:
    """
    Sends a POST request to the Deepbooru server with the encoded image and threshold.

    Args:
    encoded_string (str): The base64 encoded string of the image to be sent.
    threshold (float, optional): The threshold value. Defaults to 0.6.

    Returns:
    str | None: The response data if successful, otherwise None.
    """

    try:
        data = {"data": [encoded_string, threshold]}
        si = ServerInfo()
        async with session.post(
                si.deepbooru_url,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(data),
        ) as response:
            response.raise_for_status()  # Raise an exception for bad status codes
            response_json = await response.json()

            if 'data' in response_json:
                response_data = response_json['data'][2]

                return response_data

    except Exception as err:
        print(err)


def update_file(file_type: str, tags: Iterable, file_id: str):
    si = ServerInfo()
    stash = si.stash
    tag_ids = si.stash.map_tag_ids(tags, create=True)
    update_data = {"id": file_id, "tag_ids": tag_ids}
    if file_type == "image":
        stash.update_image(update_data)
    if file_type == "scene":
        stash.update_scene(update_data)
    if file_type == "gallery":
        stash.update_gallery(update_data)


async def main():
    file_types = ('image', 'scene')
    si = ServerInfo()
    return_amount = 100
    for l in range(0, 4):
        with tempfile.TemporaryDirectory() as temp_dir:
            for file_type in file_types:
                async with ClientSession() as session:
                    for file in get_untagged_files(file_type, return_amount=return_amount):

                        file_id = file['id']
                        url = file['paths'].get('thumbnail') or file['paths'].get('preview')
                        if url:
                            url = f"{url.split('?')[0]}?apikey={si.stash_api_key}"

                            file_data = await download_file(session=session, url=url)

                            if file_type == "scene":
                                file_name = Path(f"{temp_dir}/{file_id}.mp4")

                                async with aiofiles.open(file_name, 'wb') as f:
                                    await f.write(file_data)

                                await process_video(file_name)
                                if img_hashes := await collect_image_hashes(temp_dir, str(file_id)):
                                    tags = await handle_tags(session, img_hashes)


                            elif file_type == "image":
                                if encoded_strings := await encode_image(file_data):
                                    tags = await handle_tags(session, (encoded_strings,))

                            else:
                                break

                            if tags:
                                update_file(file_type, tags, str(file_id))


if __name__ == '__main__':
    asyncio.run(main())
