import argparse
import time
import traceback

import stashapi.log as log
from dotenv import dotenv_values, load_dotenv
from stashapi.stashapp import StashInterface


class ServerInfo:

    stash_port_nr = 9999
    deepbooru_port_nr = 7860
    try:
        load_dotenv()
        config = dotenv_values('.env')
        deepbooru_domain = config["deepbooru_domain"]
        stash_domain = config["stash_domain"]
        stash_api_key = config["stash_api_key"]
    except KeyError as key_err:
        print(key_err)
        exit(1)
    DEEPBOORU_URL = f"http://{deepbooru_domain}:{deepbooru_port_nr}/api/predict"  # replace with your API URL
    stashargs = {
        "scheme": "http",
        "host": stash_domain,
        "port": stash_port_nr,
        "logger": log,
        "ApiKey": stash_api_key
    }
    stash = StashInterface(stashargs)


def create_folder_if_not_exists():
    folder_path = "./files"
    import os
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)


def error_log(err):
    log.error(f'Error occurred: {err}')
    log.error(f"Error Type: {type(err)}")
    traceback.print_exc()


def choose_module(choice):
    if choice == '2':
        create_folder_if_not_exists()
        from process_video import run
        return run
    else:
        from process_images import run
        return run


def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    parser.add_argument('--module', type=str, default='1', help='pick one (1, 2) for Images, or Video')
    args = parser.parse_args()

    run = choose_module(args.module)
    run()


if __name__ == "__main__":
    start_time = time.time()
    try:
        main()
    except KeyboardInterrupt:
        print("execution interrupted by user")
    except Exception as main_err:
        error_log(main_err)
    end_time = time.time()
    exec_time = end_time - start_time
    print(f"it took {exec_time} seconds")
