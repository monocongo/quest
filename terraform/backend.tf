terraform {
  backend "s3" {
    bucket  = "monocongo-terraform"
    key     = "envs/quest/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
}
