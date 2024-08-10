# retrieve the S3 bucket name

```commandline
terraform apply
S3_BUCKET_NAME=$(terraform output s3_bucket_name)
echo "The S3 bucket name is: $S3_BUCKET_NAME"
```