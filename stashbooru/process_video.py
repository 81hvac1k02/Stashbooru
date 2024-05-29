import base64
import os

import requests

from stashbooru import ServerInfo


def save_video(scene_id: int) -> None:
    scene_url = f"http://{ServerInfo.stash_domain}:{ServerInfo.stash_port_nr}/scene/{scene_id}/preview?apikey={ServerInfo.stash_api_key}"
    response = requests.get(scene_url)

    if response.status_code == 200:
        # Save the video file
        with open(f'./files/{scene_id}.mp4', 'wb') as f:
            f.write(response.content)


def extract_keyframes(scene_id: int):
    import ffmpeg
    input_file = f"./files/{scene_id}.mp4"
    output_file = f"./files/keyframe_{scene_id}_%03d.jpg"
    if not os.path.isfile(input_file):
        raise FileNotFoundError(f"File {input_file} does not exist")

    try:
        (
            ffmpeg
            .input(input_file)
            .output(output_file, vf='select=eq(pict_type\\,I)', vsync='vfr')
            .run()
        )
        print(f"Keyframes extracted from {input_file} successfully.")
    except ffmpeg.Error as e:
        print(f"Error occurred: {e.stderr.decode()}")


def keyframe_to_b64(scene_id: int):
    list_of_keyframe_data = []
    for filename in os.listdir('./files'):
        if filename.startswith(f'keyframe_{scene_id}'):
            with open(f'./files/{filename}', 'rb') as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                list_of_keyframe_data.append(encoded_string)

        os.remove(f'./files/{filename}')
    return list_of_keyframe_data


def post_request(base64_string: str, threshold=0.7) -> None | str:
    import json
    data = {
        "data": [base64_string, threshold]
    }

    # async with aiohttp.ClientSession() as session:
    with requests.session() as session:
        with session.post(
                ServerInfo.DEEPBOORU_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
                data=json.dumps(data)
        ) as response:
            try:
                response_json = response.json()
                if 'data' in response_json:
                    response_data = response_json['data'][2]

                    return response_data

            except Exception as response_err:
                print(f'Error occurred: {response_err}')
    return None


def strip_tags(in_tags: str) -> list:
    new_tags = []
    tags = in_tags.split(',')
    for tag in tags:
        new_tags.append(tag.strip())
    return new_tags


def combine_lists(*args, scene_id: int) -> list[str]:
    combined_list = []

    for lst in args:
        combined_list += lst
    combined_list.append(get_existing_tag_ids(scene_id=scene_id))
    # Flatten the list of lists
    flattened_list = [item for sublist in combined_list for item in sublist]

    combined_set = set(flattened_list)  # convert the list to a set in order to remove duplicates
    return list(combined_set)


def run():
    scene_ids = get_untagged_scenes()
    print(scene_ids)
    for scene_id in scene_ids:
        save_video(scene_id)
        extract_keyframes(scene_id)
        base64_strings = keyframe_to_b64(scene_id=scene_id)
        response_data_list = []

        for base64_string in base64_strings:
            response_data = post_request(base64_string)
            if response_data is not None:
                sanitized_data = strip_tags(response_data)
                response_data_list.append(sanitized_data)

        combined_list = combine_lists(response_data_list, scene_id=scene_id)
        update = update_stash_scene(scene_id=scene_id, tags=combined_list)


def update_stash_scene(tags: list[str], scene_id: int):
    return ServerInfo.stash.update_scene({'id': scene_id, 'tags': tags}, create=True)


def get_existing_tag_ids(scene_id: int) -> list[str]:
    current_tags = ServerInfo.stash.find_scene(id=scene_id, fragment='tags{name}')
    existing_tags = [dicts.get('name') for dicts in current_tags['tags']]
    return existing_tags


def get_untagged_scenes(return_amount=5) -> list:
    less_than_amount = 3
    page_nr = 1

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
        }
    }

    scenes = ServerInfo.stash.find_scenes(filter=query, f=tag_is_null, fragment='id')

    if not scenes:  # testing if the returned amount is empty
        page_nr = page_nr + 0
        query['page'] = page_nr
        scenes = ServerInfo.stash.find_scenes(filter=query, f=tag_count, fragment='id')

    scene_ids = [i.get('id') for i in scenes]
    return scene_ids
