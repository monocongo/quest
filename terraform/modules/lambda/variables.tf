variable "bucket_name" {
  description = "The name of the S3 bucket"
  type        = string
}

variable "environment" {
  description = "The environment (e.g., dev, staging, prod)"
  type        = string
}

variable "log_bucket" {
  description = "The name of the S3 bucket for logs"
  type        = string
}
