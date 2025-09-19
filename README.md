# Imobiliare.ro Scraper

Web scraper for Romanian real estate platform (www.imobiliare.ro) using Scrapy framework. Part of the HomeAI real estate data collection system.

## Features

- 🏠 Scrapes properties for rent and sale from imobiliare.ro
- 🗺️ Geocoding support for Romanian addresses
- 💾 PostgreSQL database integration (separate `properties_romania` table)
- 🔒 AWS Parameter Store for secure configuration
- 🚀 ECS deployment ready
- 📊 Performance metrics and monitoring
- 🔄 Automatic retry and error handling
- 🚫 No image storage (as per requirements)

## Architecture

- **Separate ECS Task**: Runs independently from Swiss scrapers
- **Same ECS Cluster**: `homeai-ecs-cluster`
- **Different CloudWatch Log Group**: `/ecs/imobiliare-scraper`
- **Dedicated Database Table**: `properties_romania`
- **70% Code Reuse**: From existing Swiss scraper codebase

## Project Structure

```
ImobiliareScraper/
├── imobiliare_spiders/
│   └── scraper_core/
│       ├── spiders/
│       │   └── romania/
│       │       └── imobiliare_ro.py      # Main spider
│       ├── models.py                     # Database models
│       ├── pipelines.py                  # Data processing
│       ├── settings.py                   # Configuration
│       └── property_type_mapping_ro.py   # Romanian property types
├── migrations/
│   └── 001_create_romania_table.sql     # Database schema
├── Dockerfile
├── buildspec.yml                        # CodeBuild configuration
└── requirements.txt
```

## Installation

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/Landmarklens/ImobiliareScraper.git
cd ImobiliareScraper
```

2. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
make install
# or
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Environment Variables

For local development, create a `.env` file:

```env
# Database
DB_CONNECTION_STRING=postgresql://user:pass@localhost:5432/homeai_db

# AWS Services (optional for local)
S3_ACCESS_KEY=your_key
S3_SECRET_KEY=your_secret
S3_BUCKET_NAME=homeai-scraped-data

# Geocoding
OPEN_CAGE_API_KEY=your_api_key

# Environment
ENVIRONMENT=development
DEV_MODE=true
```

### AWS Parameter Store (Production)

All sensitive values are stored in AWS Parameter Store:

- `/homeai/prod/DB_CONNECTION_STRING` - Database connection
- `/homeai/prod/OPEN_CAGE_API_KEY` - Geocoding API
- `/homeai/prod/WEBSHARE_API_KEY` - Proxy service (optional)
- `/homeai/prod/imobiliare/API_KEY` - Imobiliare API (if available)
- `/homeai/prod/imobiliare/RATE_LIMIT` - Request rate limiting

## Usage

### Run Spider Locally

```bash
# Crawl rental properties
make crawl-rent

# Crawl properties for sale
make crawl-buy

# Custom run with parameters
scrapy crawl imobiliare_ro -a deal_type=rent -a limit=50

# Single URL mode
scrapy crawl imobiliare_ro -a single_url="https://www.imobiliare.ro/..."
```

### Available Arguments

- `deal_type`: Type of listing - "rent" or "buy" (default: "rent")
- `limit`: Maximum number of properties to scrape (default: unlimited)
- `single_url`: Scrape a single property URL

### Docker

```bash
# Build Docker image
make docker-build

# Run in Docker
make docker-run ARGS="-a deal_type=rent -a limit=20"
```

## Database Schema

The scraper uses a dedicated `properties_romania` table:

```sql
CREATE TABLE properties_romania (
    id SERIAL PRIMARY KEY,
    fingerprint VARCHAR(64) UNIQUE NOT NULL,
    external_source VARCHAR(100) DEFAULT 'imobiliare_ro',
    external_id VARCHAR(100),
    external_url VARCHAR(1000),

    -- Property details
    title VARCHAR(255),
    description TEXT,
    property_type VARCHAR(100),
    square_meters INTEGER,
    bedrooms INTEGER,
    bathrooms INTEGER,
    room_count INTEGER,

    -- Price (Romanian Lei)
    price_ron DOUBLE PRECISION,
    price_eur DOUBLE PRECISION,
    currency VARCHAR(10) DEFAULT 'RON',

    -- Location
    country VARCHAR(100) DEFAULT 'Romania',
    county VARCHAR(100),  -- Județ
    city VARCHAR(100),
    neighborhood VARCHAR(100),
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,

    -- Romanian specific
    construction_type VARCHAR(100),
    comfort_level VARCHAR(50),
    partitioning VARCHAR(50),
    energy_certificate VARCHAR(50),

    -- Features
    has_balcony BOOLEAN,
    has_terrace BOOLEAN,
    has_garage BOOLEAN,
    parking_spaces INTEGER,

    -- Metadata
    status property_status_enum,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
```

## Deployment

### ECS Deployment

The scraper runs on AWS ECS Fargate:

```bash
# Push to ECR
make push-image

# Deploy via CodePipeline (automatic on git push)
git push origin main
```

### ECS Configuration

- **Cluster**: `homeai-ecs-cluster`
- **Service**: `ImobiliareScraper-service`
- **Task Definition**: `imobiliare-scraper-task`
- **CloudWatch Logs**: `/ecs/imobiliare-scraper`

### Scheduled Execution

Configure CloudWatch Events to run the scraper periodically:

```json
{
  "ScheduleExpression": "cron(0 2 * * ? *)",
  "Target": {
    "TaskDefinitionArn": "arn:aws:ecs:region:account:task-definition/imobiliare-scraper-task"
  }
}
```

## Property Type Mapping

Romanian property types are automatically mapped to standardized English types:

- `apartament` → `apartment`
- `garsoniera` → `studio`
- `casa` → `house`
- `vila` → `villa`
- `teren` → `land`
- `spatiu comercial` → `commercial`

## Monitoring

### CloudWatch Metrics

- Items scraped per run
- Success/error rates
- Response times
- Database write throughput

### Logs

View logs in CloudWatch:
```bash
aws logs tail /ecs/imobiliare-scraper --follow
```

## Testing

```bash
# Run all tests
make test

# Run specific test
pytest tests/unit/test_spider.py -v

# Test database connection
python -m pytest tests/integration/test_database.py
```

## Development

### Adding New Fields

1. Update `models.py` with new database columns
2. Modify spider's `parse_property` method
3. Update database migration
4. Run migration: `make db-migrate`

### Debugging

```bash
# Interactive shell
scrapy shell "https://www.imobiliare.ro/..."

# Check settings
make check-settings

# View spider output without saving
scrapy crawl imobiliare_ro -L DEBUG -a limit=1
```

## Troubleshooting

### Common Issues

1. **Rate Limiting**: Adjust `DOWNLOAD_DELAY` in settings.py
2. **Geocoding Failures**: Check API key and quotas
3. **Database Connection**: Verify connection string in Parameter Store
4. **Blocked Requests**: Enable proxy rotation if needed

### Error Handling

The scraper includes automatic:
- Retry logic for failed requests
- Status detection for unavailable properties
- Duplicate detection via fingerprints
- Graceful error recovery

## Contributing

1. Create feature branch
2. Make changes
3. Run tests
4. Submit pull request

## License

Proprietary - HomeAI System

## Contact

For issues or questions, contact the HomeAI development team.