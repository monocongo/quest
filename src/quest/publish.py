import argparse
import hashlib
import os
import tempfile
from typing import List
from urllib.parse import urlparse

import boto3
from botocore.exceptions import NoCredentialsError
from bs4 import BeautifulSoup
from loguru import logger
import requests

_REQUEST_HEADERS = {
    'User-agent': 'MyApp/1.0 (https://myapp.example.com)',
}
_S3_CLIENT = boto3.client('s3')


def download_file_to_temp(
    file_url: str,
) -> str:
    """
    Download a file from the given URL to a named temporary file.

    :param file_url: URL of the file to download
    :return: Name of the temporary file
    """
    response = requests.get(file_url, headers=_REQUEST_HEADERS)
    response.raise_for_status()

    temp_file = tempfile.NamedTemporaryFile(delete=False)
    with open(temp_file.name, 'wb') as f:
        f.write(response.content)

    return temp_file.name


def list_files_from_html(
    html_content: str,
    host_url: str,
) -> List[str]:
    """
    Parse HTML content to extract file URLs.

    :param html_content: HTML content as a string
    :param host_url: Host URL, file URLs are assumed to fall under this host IP address or fully-qualified host_url name
    :return: List of file URLs
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    file_urls = [f"{host_url}{a['href']}" for a in soup.find_all('a', href=True) if not a['href'].endswith('/')]
    return file_urls


def main():
    parser = argparse.ArgumentParser(description='Upload files to S3 bucket')
    parser.add_argument('--data_url', type=str, required=True, help='URL for directory containing files to upload')
    parser.add_argument('--bucket_name', type=str, required=True, help='Name of the S3 bucket')
    args = vars(parser.parse_args())

    if os.environ.get('BUCKET_NAME'):
        args['bucket_name'] = os.environ['BUCKET_NAME']

    # sync the S3 bucket with the source directory URL, including deleting files in the S3 bucket
    sync_s3_with_source(source_url=args['data_url'], bucket_name=args['bucket_name'])


def md5_checksum(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def sync_s3_with_source(
    source_url: str,
    bucket_name: str,
) -> None:
    """
    Sync the S3 bucket with the source directory URL, including deleting files in the S3 bucket
    that are no longer present in the URL directory.

    :param source_url: directory path URL
    :param bucket_name: S3 bucket name
    :return: None
    """
    parse_result = urlparse(source_url)
    if parse_result.scheme in ('http', 'https'):
        response = requests.get(source_url, headers=_REQUEST_HEADERS)
        response.raise_for_status()

        if 'application/json' in response.headers.get('Content-Type', ''):
            file_urls = response.json()  # Assuming the URL returns a JSON list of file URLs
        else:
            # assume payload is HTML
            # TODO get this only when content type is HTML
            file_urls = list_files_from_html(
                html_content=response.text,
                host_url=f"{parse_result.scheme}://{parse_result.hostname}",
            )

        logger.info(f"Found {len(file_urls)} files in {source_url}")
        logger.info(f"Files found: {file_urls}")

        # get the list of files currently in the S3 bucket
        s3_resource = boto3.resource('s3')
        bucket = s3_resource.Bucket(bucket_name)
        s3_files = [obj.key for obj in bucket.objects.all()]

        # Get the list of file names from the URL directory
        url_file_names = [os.path.basename(urlparse(file_url).path) for file_url in file_urls]

        # Delete files in the S3 bucket that are not present in the URL directory
        for s3_file in s3_files:
            if s3_file not in url_file_names:
                s3_resource.Object(bucket_name, s3_file).delete()
                logger.info(f"Deleted {s3_file} from {bucket_name}")

        for file_url in file_urls:
            # download from the URL to a temporary file
            temp_file_path = download_file_to_temp(file_url)
            file_name = os.path.basename(urlparse(file_url).path)

            try:
                # get the checksums of the S3 object and the local file
                logger.info(f"Comparing checksum of {file_name} with S3 object")
                s3_checksum = bucket.Object(file_name).e_tag.strip('"')
                file_checksum = md5_checksum(temp_file_path)

                # Upload the file if the checksums do not match
                if file_checksum != s3_checksum:
                    logger.info(f"Different checksum for {file_name} so we're updating the S3 object")
                    upload_to_s3(temp_file_path, bucket_name, file_name)
            except s3_resource.meta.client.exceptions.ClientError:
                # the file isn't present in the bucket, so we need to upload it
                logger.info(f"File not yet present on in S3 bucket, uploading {file_name}")
                upload_to_s3(temp_file_path, bucket_name, file_name)
    else:
        msg = f'Unsupported source directory: {source_url}'
        logger.error(msg)
        raise ValueError(msg)

    logger.info(f'Successfully synced {bucket_name} with {source_url}')
    return None


def upload_to_s3(
    file_name: str,
    bucket: str,
    object_name=None,
) -> None:
    """
    Upload a file to an S3 bucket.

    :param file_name:
    :param bucket:
    :param object_name:
    :return:
    """
    if object_name is None:
        object_name = file_name

    try:
        _S3_CLIENT.upload_file(file_name, bucket, object_name)
        logger.info(f"Successfully uploaded {file_name} to s3://{bucket}/{object_name}")
    except FileNotFoundError:
        logger.error(f"The file {file_name} was not found")
    except NoCredentialsError:
        logger.error("Credentials not available")
    except Exception as e:
        logger.error(f"An error occurred during upload to S3: {str(e)}")
        raise e


if __name__ == "__main__":
    main()
