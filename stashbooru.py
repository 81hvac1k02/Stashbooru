import asyncio
import base64
import json
import logging
from typing import Iterable, Literal, Optional
import aiohttp
from dotenv import load_dotenv, dotenv_values

from stashapi.stashapp import StashInterface
import stashapi.log as log


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class ServerConfig:
    def __init__(self, env_file: str = ".env"):
        if not load_dotenv(dotenv_path=env_file):
            raise ValueError(f"File {env_file} not found")
        self.config = dotenv_values(env_file)
        try:
            self.deepbooru_domain = self.config["deepbooru_domain"]
            self.stash_domain = self.config["stash_domain"]
            self.stash_api_key = self.config["stash_api_key"]
        except KeyError as err:
            raise ValueError(f"Missing required configuration: {err}")
        self.deepbooru_port_nr = 7860
        self.stash_port_nr = 9999

    @property
    def deepbooru_url(self) -> str:
        return f"http://{self.deepbooru_domain}:{self.deepbooru_port_nr}/api/predict"

    @property
    def stash_args(self) -> dict:
        return {
            "scheme": "http",
            "host": self.stash_domain,
            "port": self.stash_port_nr,
            "logger": log,
            "ApiKey": self.stash_api_key,
        }


class DeepBooruClient:
    def __init__(self, config: ServerConfig, session: aiohttp.ClientSession = None):
        self.config = config
        self.session = session or aiohttp.ClientSession()

    async def get_tags(
        self, encoded_string: str, threshold: float = 0.6
    ) -> Optional[dict[str, str]]:
        """
        Calls the DeepBooru api to predict tags for the given encoded string.
        Returns the tag string if successful, else None.
        """
        data = {"data": [encoded_string, threshold]}

        try:
            async with self.session.post(
                self.config.deepbooru_url,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(data),
            ) as response:
                response.raise_for_status()
                response_json = await response.json()
                if "data" in response_json:
                    logger.debug(f"returned data is:\n{response_json}")
                    return response_json["data"][1]
                else:
                    logger.error(
                        "Response JSON does not contain 'data' key: %s", response_json
                    )
        except aiohttp.ClientError as err:
            logger.error("HTTP client error during get_tags: %s", err)
        except Exception as err:
            logger.error("Unexpected error during get_tags: %s", err)

        return None

    async def close(self):
        await self.session.close()


class StashClient:
    def __init__(self, config: ServerConfig):
        self.config = config
        self.stash = StashInterface(self.config.stash_args)

    def get_id_of_untagged_files(
        self, file_type: Literal["image", "scene"]
    ) -> Optional[list[dict[str, str]]]:
        """
        Returns the id for all files that are untagged in Stash for a given file type.
        """

        fragment = "id"
        tag_is_less = {"tag_count": {"modifier": "LESS_THAN", "value": 4}}

        match file_type:
            case "image":
                tag_is_less["path"] = {
                    "value": ".avif",
                    "modifier": "EXCLUDES",
                }  # avif currently fails to get parsed by deepbooru
                return self.stash.find_images(tag_is_less, fragment=fragment)
            case "scene":
                tag_is_less["framerate"] = {
                    "modifier": "GREATER_THAN",
                    "value": 0,
                }  # This filters out audio-only and broken scenes
                return self.stash.find_scenes(tag_is_less, fragment=fragment)
            case _:
                return None

    def file_url(self, file_type: str, stash_id: int):
        uri = {"image": "thumbnail", "scene": "preview"}
        return f"{self.config.stash_args['scheme']}://{self.config.stash_domain}:{self.config.stash_port_nr}/{file_type}/{stash_id}/{uri[file_type]}?apikey={self.config.stash_api_key}"

    def update_file(self, file_type: str, tags: Iterable, file_id: str):
        tag_ids = self.stash.map_tag_ids(tags, create=True)
        update_data = {"ids": [file_id], "tag_ids": {"mode": "ADD", "ids": tag_ids}}
        logger.debug(f"updating {file_type} with id {file_id} with tags: {tags}")
        match file_type:
            case "image":
                self.stash.update_images(update_data)
            case "scene":
                self.stash.update_scenes(update_data)
            case "gallery":
                self.stash.update_galleries(update_data)


# A helper function to split PNG images from a byte stream.
def split_pngs(stream: bytes) -> list[bytes]:
    # PNG signature (in bytes)
    png_sig = b"\x89PNG\r\n\x1a\n"
    # Find all the start positions of PNG files
    png_starts = []
    pos = 0
    while True:
        pos = stream.find(png_sig, pos)
        if pos == -1:
            break
        png_starts.append(pos)
        pos += len(png_sig)

    # Split the stream into individual PNG binaries.
    png_images = []
    for i, start in enumerate(png_starts):
        end = png_starts[i + 1] if i + 1 < len(png_starts) else len(stream)
        png_images.append(stream[start:end])
    return png_images


async def process_video(url: str) -> list[bytes]:
    """
    Runs ffmpeg to extract keyframes from the video at `url` as PNG images.
    """
    command = [
        "ffmpeg",
        "-loglevel",
        "warning",
        "-i",
        url,
        "-vf",
        "select=eq(pict_type\\,PICT_TYPE_I)",
        "-fps_mode",
        "vfr",
        "-f",
        "image2pipe",  # output multiple images to the pipe
        "-vcodec",
        "png",  # encode each frame as PNG images
        "pipe:1",  # write output to stdout
    ]

    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode().strip()
        raise RuntimeError(f"ffmpeg error: {error_msg}")

    # Split the stdout into separate PNG image binaries.
    return split_pngs(stdout)


async def base64_encode(png_images: list[bytes]):
    base64_frames = []
    for png_bytes in png_images:
        # Use the base64 module to encode the PNG image.
        b64_str = base64.b64encode(png_bytes).decode("ascii")
        base64_frames.append(b64_str)

    for frame in base64_frames:
        yield frame


async def get_img_data(url: str, session: aiohttp.ClientSession):
    response = session.get(url)
    response.raise_for_status()
    if response.status == 200:
        return [await response.read()]


async def main():
    config = ServerConfig()
    async with aiohttp.ClientSession() as session:
        deepbooru = DeepBooruClient(config=config, session=session)
        stash = StashClient(config=config)

        file_types = ("image", "scene")
        for file_type in file_types:
            if data_list := stash.get_id_of_untagged_files(file_type):
                for data in data_list:
                    stash_id = data["id"]
                    url = stash.file_url(file_type, stash_id)

                    match file_type:
                        case "image":
                            file_bytes = await get_img_data(url, session)
                        case "scene":
                            file_bytes = await process_video(url)
                    async for enc_str in base64_encode(file_bytes):
                        tag_set = set()
                        if tags := await deepbooru.get_tags(encoded_string=enc_str):
                            for tag in tags.keys():
                                tag_set.add(tag)
                    if tag_set:
                        stash.update_file(file_type, tag_set, stash_id)


# Example usage: run the process_video function and print list of base64 strings
if __name__ == "__main__":
    asyncio.run(main())
