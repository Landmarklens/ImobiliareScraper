.PHONY: help install test run clean docker-build docker-run crawl-rent crawl-buy db-migrate

help:
	@echo "Available commands:"
	@echo "  install        Install Python dependencies"
	@echo "  test          Run tests"
	@echo "  run           Run a specific spider (use SPIDER=imobiliare_ro)"
	@echo "  crawl-rent    Crawl rental properties"
	@echo "  crawl-buy     Crawl properties for sale"
	@echo "  clean         Clean cache and temp files"
	@echo "  docker-build  Build Docker image"
	@echo "  docker-run    Run spider in Docker"
	@echo "  db-migrate    Run database migrations"

install:
	pip install -r requirements.txt

test:
	pytest tests/ -v --cov=imobiliare_spiders --cov-report=term

run:
	@if [ -z "$(SPIDER)" ]; then \
		echo "Usage: make run SPIDER=imobiliare_ro"; \
		exit 1; \
	fi
	scrapy crawl $(SPIDER) $(ARGS)

crawl-rent:
	scrapy crawl imobiliare_ro -a deal_type=rent -a limit=100

crawl-buy:
	scrapy crawl imobiliare_ro -a deal_type=buy -a limit=100

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .scrapy
	rm -rf httpcache
	rm -rf .pytest_cache
	rm -rf .coverage

docker-build:
	docker build -t imobiliare-scraper:latest .

docker-run:
	docker run --rm \
		--env-file .env \
		-e ENVIRONMENT=development \
		imobiliare-scraper:latest \
		scrapy crawl imobiliare_ro $(ARGS)

db-migrate:
	@echo "Running database migrations..."
	psql $$DB_CONNECTION_STRING < migrations/001_create_romania_table.sql
	@echo "Migrations completed"

# Development helpers
shell:
	scrapy shell "https://www.imobiliare.ro"

check-settings:
	scrapy settings --get BOT_NAME
	scrapy settings --get CONCURRENT_REQUESTS
	scrapy settings --get DOWNLOAD_DELAY

list-spiders:
	scrapy list

# AWS deployment helpers
ecr-login:
	aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 445567083171.dkr.ecr.us-east-1.amazonaws.com

push-image: docker-build ecr-login
	docker tag imobiliare-scraper:latest 445567083171.dkr.ecr.us-east-1.amazonaws.com/home-ai-imobiliare-scraper:latest
	docker push 445567083171.dkr.ecr.us-east-1.amazonaws.com/home-ai-imobiliare-scraper:latest

# Local development with environment variables
dev-setup:
	cp .env.example .env
	@echo "Please edit .env file with your configuration"

dev-run:
	export $$(cat .env | xargs) && scrapy crawl imobiliare_ro -a limit=10