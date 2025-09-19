# Imobiliare.ro Scraper - Deployment Summary

## Overview
Complete web scraper for imobiliare.ro (Romanian real estate) with monitoring dashboard, deployed on AWS ECS Fargate.

## Components Deployed

### 1. Web Scraper
- **Technology**: Python/Scrapy
- **Container**: Running on ECS Fargate
- **Schedule**: Daily at 2:00 AM Bucharest time via EventBridge
- **Features**:
  - Full website scraping (no limits)
  - Proxy rotation via Webshare.io
  - Database storage in PostgreSQL
  - CloudWatch logging

### 2. Infrastructure
- **ECS Task Definition**: `imobiliare-scraper-task` (1024 CPU, 2048 Memory)
- **ECS Service**: `ImobiliareScraper-service`
- **ECR Repository**: `home-ai-imobiliare-scraper`
- **CI/CD Pipeline**: CodePipeline with automatic deployments on git push
- **CloudWatch Log Group**: `/ecs/imobiliare-scraper`

### 3. Database
- **Table**: `properties_romania`
- **Fields**: Romanian-specific (price_ron, county, neighborhood, etc.)
- **No image storage** (URLs only)
- **Historical price tracking enabled**

### 4. Monitoring Dashboard
- **URL**: imobiliare.homeai.ch (to be configured in DNS)
- **Authentication**: Basic auth (password protected)
- **Features**:
  - Real-time scraper run status
  - CloudWatch log viewer
  - Scraped properties statistics
  - Top 100 price drops (2-month rolling window)
  - Auto-refresh for live updates

### 5. Proxy Configuration
- **Provider**: Webshare.io
- **Middleware**: WebshareProxyMiddleware with automatic rotation
- **Refresh**: Every 3 hours
- **Retry logic**: Exponential backoff for failed requests

## AWS Resources Created

### IAM Roles
- `imobiliare-scraper-scheduler-role`: For EventBridge scheduling

### Parameter Store Entries Used
- `/HomeAiScrapper/DB_CONNECTION_STRING`
- `/HomeAiScrapper/S3_ACCESS_KEY`
- `/HomeAiScrapper/S3_SECRET_KEY`
- `/HomeAiScrapper/S3_BUCKET_NAME`
- `/HomeAiScrapper/OPEN_CAGE`
- `/HomeAiScrapper/WEBSHARE_API_KEY`
- `/HomeAiScrapper/PROXY_ENABLED`
- `/homeai/prod/imobiliare/API_KEY`
- `/homeai/prod/imobiliare/RATE_LIMIT`
- `/homeai/prod/imobiliare/USER_AGENT`

### EventBridge Schedule
- **Name**: `imobiliare-scraper-daily`
- **Expression**: `cron(0 2 * * ? *)` (2:00 AM daily)
- **Timezone**: Europe/Bucharest

## GitHub Repository
- **URL**: https://github.com/Landmarklens/ImobiliareScraper (private)
- **Auto-deploy**: Pushes to main branch trigger pipeline

## Monitoring & Logs

### CloudWatch Logs
```bash
aws logs tail /ecs/imobiliare-scraper --follow --region us-east-1
```

### Check Task Status
```bash
aws ecs list-tasks --cluster homeai-ecs-cluster --family imobiliare-scraper-task --region us-east-1
```

### Manual Run
```bash
aws ecs run-task \
    --cluster homeai-ecs-cluster \
    --task-definition imobiliare-scraper-task \
    --launch-type FARGATE \
    --network-configuration "awsvpcConfiguration={subnets=[subnet-08e155b1e47630d01],securityGroups=[sg-08b9d76f0553e6b27],assignPublicIp=ENABLED}" \
    --region us-east-1
```

## Next Steps for DNS Configuration

To make the monitoring dashboard accessible at imobiliare.homeai.ch:

1. Create CNAME record pointing to the ECS service endpoint
2. Configure Application Load Balancer if needed
3. Set up SSL certificate via ACM

## Maintenance Notes

- Proxies refresh automatically every 3 hours
- Database has proper indexes for performance
- Pipeline automatically rebuilds on code changes
- Monitoring dashboard updates in real-time
- Schedule runs daily for full website scraping