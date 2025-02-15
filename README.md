# DeepBooru & Stash API Integration
This repository contains a Python script that integrates DeepBooru for image tagging and [Stash](https://github.com/stashapp/stash) for managing and updating tags for media files. The script allows for extracting keyframes from video files as well as images, predicting tags using the DeepBooru API, and updating those tags in Stash.

Requirements
* Python 3.8+

* aiohttp library for asynchronous HTTP requests

* python-dotenv library for loading environment variables

* stashapi library for interacting with the Stash application

* ffmpeg for extracting keyframes from video files


# Configuration
Create a .env file in the root directory of your project with the following content:

* deepbooru_domain=your-deepbooru-domain
* stash_domain=your-stash-domain
* stash_api_key=your-stash-api-key

Replace your-deepbooru-domain, your-stash-domain, and your-stash-api-key with your actual configuration values.

## Docker 
Clone the repo and run 
```sh
docker compose up -d
```
