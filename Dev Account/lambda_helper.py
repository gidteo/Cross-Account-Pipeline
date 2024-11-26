import json
import boto3
import botocore
import os


ssm = boto3.client('ssm')
# sagemaker = boto3.client('sagemaker')

def lambda_handler(event, context):
    """ """
    print(event)
    print(context)
    event = event['detail']
    ####################
    # get the model_data_uri
    sagemaker_dev = boto3.client("sagemaker")
   
   # we get the latest approved model from pipeline model package
    latest_approved_model = sagemaker_dev.list_model_packages(
                                    ModelApprovalStatus=event['ModelApprovalStatus'],
                                    ModelPackageGroupName=event['ModelPackageGroupName'],
                                    SortBy='CreationTime',
                                    SortOrder='Descending'
                                )

    latest_approved_model = latest_approved_model["ModelPackageSummaryList"][0]["ModelPackageArn"]
    
    model_data_uri = sagemaker_dev.describe_model_package(
                                ModelPackageName=latest_approved_model
                            )

    model_data_uri = model_data_uri["InferenceSpecification"]["Containers"][0]["ModelDataUrl"]

    ####################
    # copy model artifact over to prod
    DevBucketName = model_data_uri[5:].split("/")[0]
    DevKey = model_data_uri[5+1+len(DevBucketName):]
    
    s3 = boto3.client("s3")
    copy_source = {'Bucket': DevBucketName, 'Key': DevKey}
    s3.copy_object(CopySource = copy_source, Bucket = os.environ["ProdBucketName"], Key = os.environ["ProdKey"]+'model.tar.gz')
    # add KMS to encrypt model in PROD 
    # KMS sits in PROD and will need to give DEV account permission to use that key to encrypt

    ####################
    # assume PROD 
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(
        RoleArn=os.environ["ProdExecRole"], ## This is PROD account role (this account)
        RoleSessionName="cross_acct_lambda"
    )
    
    new_session = boto3.Session(aws_access_key_id=acct_b['Credentials']['AccessKeyId'],
                  aws_secret_access_key=acct_b['Credentials']['SecretAccessKey'],
                  aws_session_token=acct_b['Credentials']['SessionToken'])
    
    ####################
    # create model pacakge group name in PROD 
    """
    if model package group name is not present in prod, it will fail
    """
    sagemaker_prod = new_session.client("sagemaker")
    try:
        res = sagemaker_prod.describe_model_package_group(
            ModelPackageGroupName=event["ModelPackageGroupName"]
        )
        print(res)
        
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == 'ValidationException' and ('does not exist' in error.response['Error']["Message"]):
            sagemaker_prod.create_model_package_group(
            ModelPackageGroupName=event["ModelPackageGroupName"],
        )
        else:
            raise error
        
    except Exceptions as e:
        raise e
    
    ####################    
    # create model package in PROD
    res = sagemaker_prod.create_model_package(
        ModelPackageGroupName=event["ModelPackageGroupName"],
        InferenceSpecification={
                'Containers': [
                    {
                        'Image': event['InferenceSpecification']['Containers'][0].get("Image", "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-xgboost:1.0-1-cpu-py3"),
                        'ModelDataUrl': event['InferenceSpecification']['Containers'][0].get("ModelDataUrl", None),
                        'Environment': {},
                    },
                ],
                'SupportedTransformInstanceTypes':event['InferenceSpecification']["SupportedTransformInstanceTypes"],
                'SupportedContentTypes':event['InferenceSpecification']["SupportedContentTypes"],
                'SupportedResponseMIMETypes': event['InferenceSpecification']["SupportedResponseMIMETypes"],
            },
            # InferenceSpecification=event['InferenceSpecification'],
            CertifyForMarketplace=False,
            ModelApprovalStatus='Approved',
            ModelMetrics={
                'ModelQuality': {
                    'Statistics': {
                        'ContentType': event['ModelMetrics']['ModelQuality']["Statistics"]["ContentType"],
                        'S3Uri': event['ModelMetrics']["ModelQuality"]["Statistics"]["S3Uri"]
                    },
                },
                'Bias': {},
                'Explainability': {}
            },
            # ModelMetrics=event['ModelMetrics']
        )

    ####################
    # create model in PROD
    try:
        # res = sagemaker_prod.create_model(
        #     ModelName=os.environ["ModelName"],
        #     PrimaryContainer={
        #         'Image': event["Image"],
        #         'ModelDataUrl': event["ModelDataUrl"],
        #         'Environment': {},
        #     },
        #     ExecutionRoleArn=event["ProdExecRole"],
        #     EnableNetworkIsolation=False
        # )
        response = sagemaker_prod.create_model(
        ModelName=event['ModelPackageGroupName'].split('/')[0],
        Containers = [
            {"ModelPackageName": res['ModelPackageArn'] }
                ],
        ExecutionRoleArn=os.environ["ProdExecRole"],
        EnableNetworkIsolation=False),
        
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == 'ValidationException' and ('Cannot create already existing model' in error.response['Error']["Message"]):
            # delete model
            sagemaker_prod.delete_model(
              ModelName=event['ModelPackageGroupName'].split('/')[0],
                )
            # create model again
            sagemaker_prod.create_model(
            ModelName=event['ModelPackageGroupName'].split('/')[0],
        Containers = [
            {"ModelPackageName": res['ModelPackageArn'] }
                ],
        ExecutionRoleArn=os.environ["ProdExecRole"],
        EnableNetworkIsolation=False
        ),
        else:
            raise error
        
    except Exception as e:
        raise e
    
    ####################
    # create SSM parameter in PROD
    ssm = new_session.client("ssm")
    ssm.put_parameter(
            Name = 'model_name',
            Value= event["ModelPackageGroupName"].split('/')[0],
            Type='String',
            Overwrite=True
    )
    
    return {
        "statusCode": 200,
        "body": json.dumps("Created lambda step!"),

    }
