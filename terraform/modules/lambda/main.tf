# generate a random string to be used as a suffix for the S3 bucket name
resource "random_string" "bucket_suffix" {
  length  = 12
  special = false
  upper   = false
}

# creates an S3 bucket with a name that includes the generated random string suffix, tag with a name and environment
resource "aws_s3_bucket" "data_bucket" {
  bucket = "${var.bucket_name}-${random_string.bucket_suffix.result}"

  tags = {
    Name        = "${var.bucket_name} S3 Bucket"
    Environment = var.environment
  }
}

# configure the S3 bucket to block public access
resource "aws_s3_bucket_public_access_block" "data_bucket_public_access" {
  bucket = aws_s3_bucket.data_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# enable versioning on the S3 bucket
resource "aws_s3_bucket_versioning" "data_bucket_versioning" {
  bucket = aws_s3_bucket.data_bucket.id

  versioning_configuration {
    status = "Enabled"
  }
}

# configure server-side encryption on the S3 bucket
resource "aws_s3_bucket_server_side_encryption_configuration" "data_bucket_sse" {
  bucket = aws_s3_bucket.data_bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# configure logging on the S3 bucket to send access logs to a separate log bucket
resource "aws_s3_bucket_logging" "data_bucket_logging" {
  bucket        = aws_s3_bucket.data_bucket.id
  target_bucket = var.log_bucket
  target_prefix = "log/"
}

# configure a lifecycle policy on the S3 bucket to transition objects
# to Glacier storage class after 30 days and expire after 365 days
resource "aws_s3_bucket_lifecycle_configuration" "data_bucket_lifecycle" {
  bucket = aws_s3_bucket.data_bucket.id

  rule {
    id     = "log"
    status = "Enabled"

    filter {
      prefix = "log/"
    }

    transition {
      days          = 30
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }
  }
}

# configure a bucket policy to deny unencrypted requests to the S3 bucket
resource "aws_s3_bucket_policy" "data_bucket_policy" {
  bucket = aws_s3_bucket.data_bucket.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.data_bucket.arn,
          "${aws_s3_bucket.data_bucket.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}

# output the name of the created S3 bucket
output "s3_bucket_name" {
  description = "The name of the created S3 bucket"
  value       = aws_s3_bucket.data_bucket.id
}

# An IAM role for the Lambda function is created using the aws_iam_role resource.
# This role allows the Lambda function to assume the necessary permissions to execute.
# The `assume_role_policy` is defined to allow the Lambda service to assume this role.
resource "aws_iam_role" "lambda_role" {
  name = "lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# An IAM role policy is attached to the Lambda role.
# This policy grants permissions to interact with S3 and CloudWatch Logs.
resource "aws_iam_role_policy" "lambda_policy" {
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "*"
      }
    ]
  })
}

# ensure the layer directory exists
resource "null_resource" "create_layer_directory" {
  provisioner "local-exec" {
    command = "mkdir -p ${path.module}/../../../layer/python"
  }
}

# install the dependencies for the Lambda function in a separate layer folder
# which will subsequently be used as the source for the layer ZIP archive
resource "null_resource" "install_layer_dependencies" {
  triggers = {
    requirements_txt = filemd5("${path.module}/../../../requirements.txt")
  }

  # use a local-exec provisioner to run the pip install command that places the dependencies into the layer folder
  provisioner "local-exec" {
    command = "pip install -r ${path.module}/../../../requirements.txt --target ${path.module}/../../../layer/python/"
  }

  depends_on = [null_resource.create_layer_directory]
}

# create a ZIP archive of the layer code
data "archive_file" "layer_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../layer"
  output_path = "${path.module}/../../../archive/layer.zip"
  excludes    = ["**/__pycache__/**"]
  depends_on = [null_resource.install_layer_dependencies]
}

# create a ZIP archive of the Lambda function code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src/quest"
  output_path = "${path.module}/../../../archive/lambda.zip"
  excludes    = ["**/__pycache__/**"]
}

# define the Lambda layer using the ZIP archive created earlier
resource "aws_lambda_layer_version" "lambda_layer" {
  filename   = data.archive_file.layer_zip.output_path
  layer_name = "lambda-layer"
  compatible_runtimes = ["python3.12"]
}

# Define the Lambda function itself, specifying the function's name, runtime, handler, and the role it will use.
# The function's code is provided as a ZIP file, and environment variables are set.
resource "aws_lambda_function" "sync_function" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "sync_function"
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.handler"
  runtime          = "python3.12"
  layers           = [aws_lambda_layer_version.lambda_layer.arn]
  source_code_hash = filebase64sha256(data.archive_file.lambda_zip.output_path)
  timeout          = 600

  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.data_bucket.bucket
    }
  }
}

# CloudWatch Event Rule to trigger the Lambda function on a daily schedule
resource "aws_cloudwatch_event_rule" "daily_rule" {
  name                = "daily_rule"
  schedule_expression = "rate(1 day)"
}

# link the CloudWatch Event Rule to the Lambda function
resource "aws_cloudwatch_event_target" "lambda_target" {
  rule = aws_cloudwatch_event_rule.daily_rule.name
  arn  = aws_lambda_function.sync_function.arn
}

# add a permission to allow CloudWatch to invoke the Lambda function
resource "aws_lambda_permission" "allow_cloudwatch" {
  statement_id  = "AllowExecutionFromCloudWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sync_function.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_rule.arn
}

# SQS queue to receive notification messages from the S3 bucket
resource "aws_sqs_queue" "data_queue" {
  name = "data_queue"
}

# # S3 bucket notification to send events to the SQS queue whenever an object is created in the bucket
# resource "aws_s3_bucket_notification" "bucket_notification" {
#   bucket = aws_s3_bucket.data_bucket.id
#
#   queue {
#     queue_arn = aws_sqs_queue.data_queue.arn
#     events    = ["s3:ObjectCreated:*"]
#   }
# }
