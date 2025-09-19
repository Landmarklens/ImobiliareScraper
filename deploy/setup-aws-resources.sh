#!/bin/bash

# AWS Infrastructure Setup Script for ImobiliareScraper
# This script creates all necessary AWS resources for the Romanian property scraper

set -e

echo "Setting up AWS resources for ImobiliareScraper..."

# Configuration
AWS_REGION="us-east-1"
AWS_ACCOUNT_ID="445567083171"
ECR_REPOSITORY="home-ai-imobiliare-scraper"
CLUSTER_NAME="homeai-ecs-cluster"
SERVICE_NAME="ImobiliareScraper-service"
TASK_FAMILY="imobiliare-scraper-task"
LOG_GROUP="/ecs/imobiliare-scraper"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

# 1. Create ECR Repository
echo "Creating ECR repository..."
aws ecr create-repository \
    --repository-name ${ECR_REPOSITORY} \
    --region ${AWS_REGION} \
    --image-scanning-configuration scanOnPush=true \
    2>/dev/null || print_warning "ECR repository might already exist"
print_status "ECR repository ready: ${ECR_REPOSITORY}"

# 2. Create CloudWatch Log Group
echo "Creating CloudWatch log group..."
aws logs create-log-group \
    --log-group-name ${LOG_GROUP} \
    --region ${AWS_REGION} \
    2>/dev/null || print_warning "Log group might already exist"
print_status "CloudWatch log group created: ${LOG_GROUP}"

# 3. Create Parameter Store entries
echo "Creating Parameter Store entries..."

# Romania specific parameters
aws ssm put-parameter \
    --name "/homeai/prod/imobiliare/RATE_LIMIT" \
    --value "1.0" \
    --type "String" \
    --overwrite \
    --region ${AWS_REGION} \
    2>/dev/null || true

aws ssm put-parameter \
    --name "/homeai/prod/imobiliare/USER_AGENT" \
    --value "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
    --type "String" \
    --overwrite \
    --region ${AWS_REGION} \
    2>/dev/null || true

# Add API key placeholder (will need to be updated with actual value)
aws ssm put-parameter \
    --name "/homeai/prod/imobiliare/API_KEY" \
    --value "placeholder_update_with_actual_key" \
    --type "SecureString" \
    --overwrite \
    --region ${AWS_REGION} \
    2>/dev/null || true

print_status "Parameter Store entries created"

# 4. Create CodeBuild Projects
echo "Creating CodeBuild projects..."

# Build Project
cat > /tmp/codebuild-build-project.json << EOF
{
    "name": "ImobiliareScraper-Build",
    "source": {
        "type": "CODEPIPELINE",
        "buildspec": "buildspec.yml"
    },
    "artifacts": {
        "type": "CODEPIPELINE"
    },
    "environment": {
        "type": "LINUX_CONTAINER",
        "image": "aws/codebuild/standard:5.0",
        "computeType": "BUILD_GENERAL1_SMALL",
        "privilegedMode": true,
        "environmentVariables": [
            {
                "name": "AWS_DEFAULT_REGION",
                "value": "${AWS_REGION}"
            },
            {
                "name": "AWS_ACCOUNT_ID",
                "value": "${AWS_ACCOUNT_ID}"
            },
            {
                "name": "IMAGE_REPO_NAME",
                "value": "${ECR_REPOSITORY}"
            }
        ]
    },
    "serviceRole": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/service-role/codebuild-service-role"
}
EOF

aws codebuild create-project \
    --cli-input-json file:///tmp/codebuild-build-project.json \
    --region ${AWS_REGION} \
    2>/dev/null || print_warning "Build project might already exist"

# Test Project
cat > /tmp/codebuild-test-project.json << EOF
{
    "name": "ImobiliareScraper-Test",
    "source": {
        "type": "CODEPIPELINE",
        "buildspec": "buildspec-test.yml"
    },
    "artifacts": {
        "type": "CODEPIPELINE"
    },
    "environment": {
        "type": "LINUX_CONTAINER",
        "image": "aws/codebuild/standard:5.0",
        "computeType": "BUILD_GENERAL1_SMALL"
    },
    "serviceRole": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/service-role/codebuild-service-role"
}
EOF

aws codebuild create-project \
    --cli-input-json file:///tmp/codebuild-test-project.json \
    --region ${AWS_REGION} \
    2>/dev/null || print_warning "Test project might already exist"

print_status "CodeBuild projects created"

# 5. Create ECS Task Definition
echo "Creating ECS task definition..."

cat > /tmp/task-definition.json << EOF
{
    "family": "${TASK_FAMILY}",
    "taskRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
    "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "512",
    "memory": "1024",
    "containerDefinitions": [
        {
            "name": "Imobiliarescraper",
            "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}:latest",
            "essential": true,
            "environment": [
                {
                    "name": "ENVIRONMENT",
                    "value": "production"
                },
                {
                    "name": "SCRAPER_NAME",
                    "value": "imobiliare_ro"
                },
                {
                    "name": "COUNTRY",
                    "value": "romania"
                }
            ],
            "secrets": [
                {
                    "name": "DB_CONNECTION_STRING",
                    "valueFrom": "/homeai/prod/DB_CONNECTION_STRING"
                },
                {
                    "name": "S3_ACCESS_KEY",
                    "valueFrom": "/homeai/prod/S3_ACCESS_KEY"
                },
                {
                    "name": "S3_SECRET_KEY",
                    "valueFrom": "/homeai/prod/S3_SECRET_KEY"
                },
                {
                    "name": "S3_BUCKET_NAME",
                    "valueFrom": "/homeai/prod/S3_BUCKET_NAME"
                },
                {
                    "name": "OPEN_CAGE_API_KEY",
                    "valueFrom": "/homeai/prod/OPEN_CAGE_API_KEY"
                },
                {
                    "name": "WEBSHARE_API_KEY",
                    "valueFrom": "/homeai/prod/WEBSHARE_API_KEY"
                },
                {
                    "name": "PROXY_ENABLED",
                    "valueFrom": "/homeai/prod/PROXY_ENABLED"
                },
                {
                    "name": "SCRAPEOPS_API_KEY",
                    "valueFrom": "/homeai/prod/SCRAPEOPS_API_KEY"
                },
                {
                    "name": "IMOBILIARE_API_KEY",
                    "valueFrom": "/homeai/prod/imobiliare/API_KEY"
                },
                {
                    "name": "IMOBILIARE_RATE_LIMIT",
                    "valueFrom": "/homeai/prod/imobiliare/RATE_LIMIT"
                },
                {
                    "name": "IMOBILIARE_USER_AGENT",
                    "valueFrom": "/homeai/prod/imobiliare/USER_AGENT"
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "${LOG_GROUP}",
                    "awslogs-region": "${AWS_REGION}",
                    "awslogs-stream-prefix": "ecs"
                }
            },
            "command": ["scrapy", "crawl", "imobiliare_ro", "-a", "deal_type=rent"]
        }
    ]
}
EOF

aws ecs register-task-definition \
    --cli-input-json file:///tmp/task-definition.json \
    --region ${AWS_REGION}

print_status "ECS task definition registered"

# 6. Get VPC and Subnet information
echo "Getting VPC configuration..."
VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text --region ${AWS_REGION})
SUBNET_IDS=$(aws ec2 describe-subnets --filters "Name=vpc-id,Values=${VPC_ID}" --query "Subnets[*].SubnetId" --output text --region ${AWS_REGION})
SUBNET_ID=$(echo ${SUBNET_IDS} | cut -d' ' -f1)

# Get or create security group
SECURITY_GROUP_ID=$(aws ec2 describe-security-groups \
    --filters "Name=group-name,Values=ecs-scraper-sg" \
    --query "SecurityGroups[0].GroupId" \
    --output text \
    --region ${AWS_REGION} 2>/dev/null || echo "")

if [ -z "${SECURITY_GROUP_ID}" ] || [ "${SECURITY_GROUP_ID}" == "None" ]; then
    echo "Creating security group..."
    SECURITY_GROUP_ID=$(aws ec2 create-security-group \
        --group-name ecs-scraper-sg \
        --description "Security group for ECS scraper tasks" \
        --vpc-id ${VPC_ID} \
        --query 'GroupId' \
        --output text \
        --region ${AWS_REGION})

    # Add outbound rule for HTTPS
    aws ec2 authorize-security-group-egress \
        --group-id ${SECURITY_GROUP_ID} \
        --protocol tcp \
        --port 443 \
        --cidr 0.0.0.0/0 \
        --region ${AWS_REGION} 2>/dev/null || true
fi

print_status "VPC configuration ready"

# 7. Create ECS Service
echo "Creating ECS service..."

cat > /tmp/ecs-service.json << EOF
{
    "serviceName": "${SERVICE_NAME}",
    "taskDefinition": "${TASK_FAMILY}",
    "desiredCount": 0,
    "launchType": "FARGATE",
    "networkConfiguration": {
        "awsvpcConfiguration": {
            "subnets": ["${SUBNET_ID}"],
            "securityGroups": ["${SECURITY_GROUP_ID}"],
            "assignPublicIp": "ENABLED"
        }
    }
}
EOF

aws ecs create-service \
    --cluster ${CLUSTER_NAME} \
    --cli-input-json file:///tmp/ecs-service.json \
    --region ${AWS_REGION} \
    2>/dev/null || print_warning "Service might already exist"

print_status "ECS service created"

# 8. Create CloudWatch Events Rule for scheduled execution
echo "Creating CloudWatch Events rule for scheduled execution..."

# Create rule for daily execution at 2 AM UTC
aws events put-rule \
    --name imobiliare-scraper-daily \
    --schedule-expression "cron(0 2 * * ? *)" \
    --state ENABLED \
    --description "Daily execution of ImobiliareScraper" \
    --region ${AWS_REGION}

# Create IAM role for CloudWatch Events (if not exists)
cat > /tmp/events-trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "events.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

aws iam create-role \
    --role-name ecsEventsRole-ImobiliareScraper \
    --assume-role-policy-document file:///tmp/events-trust-policy.json \
    2>/dev/null || print_warning "Events role might already exist"

# Attach policy to role
aws iam put-role-policy \
    --role-name ecsEventsRole-ImobiliareScraper \
    --policy-name ECSEventPolicy \
    --policy-document "{
        \"Version\": \"2012-10-17\",
        \"Statement\": [
            {
                \"Effect\": \"Allow\",
                \"Action\": [
                    \"ecs:RunTask\"
                ],
                \"Resource\": \"arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:task-definition/${TASK_FAMILY}:*\"
            },
            {
                \"Effect\": \"Allow\",
                \"Action\": \"iam:PassRole\",
                \"Resource\": \"*\"
            }
        ]
    }"

# Add target to rule
aws events put-targets \
    --rule imobiliare-scraper-daily \
    --targets "Id"="1","Arn"="arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:cluster/${CLUSTER_NAME}","RoleArn"="arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsEventsRole-ImobiliareScraper","EcsParameters"="{\"TaskDefinitionArn\":\"arn:aws:ecs:${AWS_REGION}:${AWS_ACCOUNT_ID}:task-definition/${TASK_FAMILY}\",\"TaskCount\":1,\"LaunchType\":\"FARGATE\",\"NetworkConfiguration\":{\"awsvpcConfiguration\":{\"Subnets\":[\"${SUBNET_ID}\"],\"SecurityGroups\":[\"${SECURITY_GROUP_ID}\"],\"AssignPublicIp\":\"ENABLED\"}}}" \
    --region ${AWS_REGION}

print_status "CloudWatch Events rule created for daily execution"

# Clean up temporary files
rm -f /tmp/codebuild-*.json /tmp/task-definition.json /tmp/ecs-service.json /tmp/events-trust-policy.json

echo ""
print_status "AWS infrastructure setup complete!"
echo ""
echo "Next steps:"
echo "1. Run database migration: psql \$DB_CONNECTION_STRING < migrations/001_create_romania_table.sql"
echo "2. Build and push Docker image: make push-image"
echo "3. Create GitHub repository and push code"
echo "4. Set up CodePipeline using the pipeline_config.json"
echo ""
echo "Service details:"
echo "  ECR Repository: ${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"
echo "  ECS Service: ${SERVICE_NAME}"
echo "  CloudWatch Logs: ${LOG_GROUP}"
echo "  Scheduled Execution: Daily at 2 AM UTC"