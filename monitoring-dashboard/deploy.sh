#!/bin/bash

# Deploy monitoring dashboard to ECS

echo "Building Docker image for monitoring dashboard..."
docker build -t imobiliare-monitoring-dashboard .

# Tag and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 445567083171.dkr.ecr.us-east-1.amazonaws.com
docker tag imobiliare-monitoring-dashboard:latest 445567083171.dkr.ecr.us-east-1.amazonaws.com/imobiliare-monitoring:latest
docker push 445567083171.dkr.ecr.us-east-1.amazonaws.com/imobiliare-monitoring:latest

# Create task definition for monitoring dashboard
cat > /tmp/monitoring-task-definition.json << EOF
{
    "family": "imobiliare-monitoring-task",
    "taskRoleArn": "arn:aws:iam::445567083171:role/ecsTaskExecutionRole",
    "executionRoleArn": "arn:aws:iam::445567083171:role/ecsTaskExecutionRole",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "256",
    "memory": "512",
    "containerDefinitions": [
        {
            "name": "monitoring-dashboard",
            "image": "445567083171.dkr.ecr.us-east-1.amazonaws.com/imobiliare-monitoring:latest",
            "essential": true,
            "portMappings": [
                {
                    "containerPort": 3000,
                    "protocol": "tcp"
                }
            ],
            "environment": [
                {
                    "name": "PORT",
                    "value": "3000"
                }
            ],
            "secrets": [
                {
                    "name": "ADMIN_PASSWORD",
                    "valueFrom": "/homeai/monitoring/ADMIN_PASSWORD"
                }
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/imobiliare-monitoring",
                    "awslogs-region": "us-east-1",
                    "awslogs-stream-prefix": "ecs"
                }
            }
        }
    ]
}
EOF

# Register task definition
aws ecs register-task-definition --cli-input-json file:///tmp/monitoring-task-definition.json --region us-east-1

# Create service
aws ecs create-service \
    --cluster homeai-ecs-cluster \
    --service-name imobiliare-monitoring-service \
    --task-definition imobiliare-monitoring-task:1 \
    --desired-count 1 \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-08e155b1e47630d01],securityGroups=[sg-08b9d76f0553e6b27],assignPublicIp=ENABLED}" \
    --region us-east-1

echo "Monitoring dashboard deployed!"