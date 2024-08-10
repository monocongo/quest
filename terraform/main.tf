provider "aws" {
  region = var.region
}

module "lambda" {
  source      = "./modules/lambda"
  bucket_name = var.bucket_name
  environment = var.environment
  log_bucket  = var.log_bucket
}
