import json
import boto3
import botocore


ssm = boto3.client('ssm')
# sagemaker = boto3.client('sagemaker')

def lambda_handler(event, context):
    """ """
    print(event)
    print(context)
    
    ####################
    # get the model_data_uri
    sagemaker_dev = boto3.client("sagemaker")
    pipeline_arn = sagemaker_dev.list_pipeline_executions(
        PipelineName=event["PipelineName"])
    pipeline_arn = pipeline_arn["PipelineExecutionSummaries"][0]["PipelineExecutionArn"]
    
    response = sagemaker_dev.list_pipeline_execution_steps(
        PipelineExecutionArn=pipeline_arn,
        SortOrder='Ascending')
        
    training_arn = response["PipelineExecutionSteps"][int(event["TrainingEventSequence"])]["Metadata"]["TrainingJob"]["Arn"]    
    training_job_name = training_arn.rsplit('/', 1)[-1]

    model_data_uri = sagemaker_dev.describe_training_job(
    TrainingJobName=training_job_name
            )

    model_data_uri = model_data_uri["ModelArtifacts"]["S3ModelArtifacts"]
   

    ####################
    # copy model artifact over to prod
    DevBucketName = model_data_uri[5:].split("/")[0]
    DevKey = model_data_uri[5+1+len(DevBucketName):]
    
    s3 = boto3.client("s3")
    copy_source = {'Bucket': DevBucketName, 'Key': DevKey}
    s3.copy_object(CopySource = copy_source, Bucket = event["ProdBucketName"], Key = event["ProdKey"]+'model.tar.gz')
    # add KMS to encrypt model in PROD 
    # KMS sits in PROD and will need to give DEV account permission to use that key to encrypt

    ####################
    # assume PROD 
    sts_connection = boto3.client('sts')
    acct_b = sts_connection.assume_role(
        RoleArn=event["ProdExecRole"], ## This is PROD account role (this account)
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
            ModelPackageGroupName=ModelPackage_GroupName,
        )
        else:
            raise error
        
    except Exceptions as e:
        raise e
    
    ####################    
    # create model package in PROD
    sagemaker_prod.create_model_package(
        ModelPackageGroupName=event["ModelPackageGroupName"],
        InferenceSpecification={
                'Containers': [
                    {
                        'ContainerHostname': event["ContainerHostname"],
                        'Image': event["Image"],
                        'ModelDataUrl': event["model_data_uri"],
                        'Environment': {},
                    },
                ],
                'SupportedTransformInstanceTypes': [
                    event["SupportedTransformInstanceTypes"]
                ],
                'SupportedContentTypes': [
                    event["CSV_type"],
                ],
                'SupportedResponseMIMETypes': [
                    event["CSV_type"],
                ]
            },
            CertifyForMarketplace=False,
            ModelApprovalStatus='Approved',
            ModelMetrics={
                'ModelQuality': {
                    'Statistics': {
                        'ContentType': event["JSON_application"],
                        'S3Uri': event["EvaluationPath"]+'evaluation.json'
                    },
                },
                'Bias': {},
                'Explainability': {}
            },
        )

    ####################
    # create model in PROD
    try:
        res = sagemaker_prod.create_model(
            ModelName=event["model_name"],
            PrimaryContainer={
                'Image': event["Image"],
                'ModelDataUrl': event["model_data_uri"],
                'Environment': {},
            },
            ExecutionRoleArn=event["ProdExecRole"],
            EnableNetworkIsolation=False
        )
        
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == 'ValidationException' and ('Cannot create already existing model' in error.response['Error']["Message"]):
            # delete model
            sagemaker_prod.delete_model(
              ModelName=event["model_name"]
                )
            # create model again
            sagemaker_prod.create_model(
            ModelName=event["model_name"],
            PrimaryContainer={
                'Image': event["Image"],
                'ModelDataUrl': event["model_data_uri"],
                'Environment': {},
            },
            ExecutionRoleArn=event["ProdExecRole"],
            EnableNetworkIsolation=False
        )
        else:
            raise error
        
    except Exceptions as e:
        raise e
    
    ####################
    # create SSM parameter in PROD
    ssm = new_session.client("ssm")
    ssm.put_parameter(
            Name = 'model_name',
            Value= event["model_name"],
            Type='String',
            Overwrite=True
    )
    
    return {
        "statusCode": 200,
        "body": json.dumps("Created lambda step!"),

    }
