import argparse
import json
import os

from loguru import logger
import pandas as pd

from fetch import fetch_api_data
from publish import sync_s3_with_source


def handle_analysis(event, context):
    """

    :param event:
    :param context:
    :return:
    """
    # bucket name environment variable should be set by Terraform for the Lambda function
    bucket_name = os.environ['BUCKET_NAME']

    try:
        logger.info('Handling SQS message')

        # extract and clean the population data
        json_path = f"s3://{bucket_name}/api_data.json"
        pop_df = pd.read_json(path_or_buf=json_path)
        pop_df = pop_df.rename(columns=lambda x: x.strip().lower())

        # extract and clean the BLS data
        csv_path = f"s3://{bucket_name}/pr.data.0.Current"
        bls_df = pd.read_csv(filepath_or_buffer=csv_path, sep='\t')
        bls_df = bls_df.rename(columns=lambda x: x.strip().lower())
        for col in ['series_id', 'period']:
            bls_df[col] = bls_df[col].str.strip()

        # perform analysis on the data
        mean = pop_df['population'].where(pop_df['year'].between(2013, 2018, inclusive='both')).mean()
        std_dev = pop_df['population'].where(pop_df['year'].between(2013, 2018, inclusive='both')).std()
        result = [f"Mean population: {mean:.2f}", f"Standard deviation: {std_dev:.2f}"]

        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }

    except Exception as e:
        print(e)
        return {
            'statusCode': 500,
            'body': json.dumps(f'Data processing failed: {str(e)}')
        }


def handle_sync(event, context):
    """
    Lambda function handler to fetch and load data from 1) a download URL and 2) a REST API.

    :param event:
    :param context:
    :return:
    """
    data_url = 'https://download.bls.gov/pub/time.series/pr/'
    api_url = 'https://datausa.io/api/data?drilldowns=Nation&measures=Population'
    s3_file_name = 'api_data.json'

    # bucket name environment variable should be set by Terraform for the Lambda function
    bucket_name = os.environ['BUCKET_NAME']

    try:
        logger.info('Syncing data from download site')
        sync_s3_with_source(source_url=data_url, bucket_name=bucket_name)
        logger.info('Fetching data from API')
        fetch_api_data(api_url=api_url, bucket_name=bucket_name, s3_file_name=s3_file_name)

        return {
            'statusCode': 200,
            'body': json.dumps('Data processing completed')
        }

    except Exception as e:
        print(e)
        return {
            'statusCode': 500,
            'body': json.dumps(f'Data processing failed: {str(e)}')
        }


def main():
    # parse the CLI arguments
    parser = argparse.ArgumentParser(description='Upload files to S3 bucket')
    parser.add_argument('--api_url', type=str, required=True, help='URL for the data API')
    parser.add_argument('--data_url', type=str, required=True, help='URL for the data download')
    parser.add_argument('--bucket_name', type=str, required=True, help='Name of the S3 bucket')
    parser.add_argument('--s3_file_name', type=str, required=True, help='Readable name for the file on S3')
    args = vars(parser.parse_args())

    if os.environ.get('BUCKET_NAME'):
        args['bucket_name'] = os.environ['BUCKET_NAME']

    # sync the S3 then fetch data from API
    sync_s3_with_source(source_url=args['data_url'], bucket_name=args['bucket_name'])
    fetch_api_data(api_url=args['api_url'], bucket_name=args['bucket_name'], s3_file_name=args['s3_file_name'])

    return 0


if __name__ == '__main__':
    main()
