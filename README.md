# MLC_Pipeline_PoC
Pipeline proof of concept

## Dev Account
In Dev account, we have a pipeline that does Processing, Training and Evaluation. We also have a Lambda Function that will be triggered once the model gets approved by MLC personnel.
The Lambda Function does the following:
  1. get the model_data_uri
  2. copy mdoel artifact from DEV s3 to PROD s3
  3. then, we assume PROD execution role
  4. create model package group name in PROD
  5. create model package in PROD
  6. create SageMaker model in PROD
  7. create SSM parameter in PROD

## Prod Account
In Prod account, we will have a lambda step that will get the latest model name that is stored in SSM parameter. Then, we returned the latest model name and use it to deploy Batch Transform Job in Pipeline.
