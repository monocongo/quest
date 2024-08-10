import argparse
import json
from tempfile import NamedTemporaryFile
import os

from loguru import logger
import requests

from publish import upload_to_s3


def fetch_api_data(
    api_url: str,
    bucket_name: str,
    s3_file_name: str,
) -> int:
    """
    Fetch data from an API URL.

    :param api_url: URL of the API to fetch data from
    :param bucket_name: Name of the S3 bucket to upload data to
    :param s3_file_name: Name of the file to upload to S3
    :return: 0 if successful, 1 if failed
    """
    logger.info(f"Fetching data from {api_url}")
    response = requests.get(api_url)
    if response.status_code == 200:
        data = response.json()['data']
    else:
        logger.error(f"Failed to fetch data from {api_url}")
        return 1

    # save the data as a temporary JSON file
    with NamedTemporaryFile(mode='w', delete=False) as temp_file:
        json.dump(data, temp_file)
        temp_file.flush()  # ensure all data is written to the file
        temp_file_path = temp_file.name

    # rename the temporary file to a more readable name
    readable_file_path = f"{temp_file_path}.json"
    os.rename(temp_file_path, readable_file_path)

    # upload the renamed file to S3
    upload_to_s3(readable_file_path, bucket_name, s3_file_name)

    # log the upload and return success
    logger.info(f"Data uploaded from {api_url} to s3://{bucket_name}/{s3_file_name}")
    return 0


def main():
    # parse the CLI arguments
    parser = argparse.ArgumentParser(description='Upload files to S3 bucket')
    parser.add_argument('--api_url', type=str, required=True, help='URL for the data API')
    parser.add_argument('--bucket_name', type=str, required=True, help='Name of the S3 bucket')
    parser.add_argument('--s3_file_name', type=str, required=True, help='Readable name for the file on S3')
    args = vars(parser.parse_args())

    if os.environ.get('BUCKET_NAME'):
        args['bucket_name'] = os.environ['BUCKET_NAME']

    # fetch data from API
    return fetch_api_data(api_url=args['api_url'], bucket_name=args['bucket_name'], s3_file_name=args['s3_file_name'])


if __name__ == '__main__':
    main()
