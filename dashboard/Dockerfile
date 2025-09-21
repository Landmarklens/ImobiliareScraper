FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY templates/ templates/

# Expose port
EXPOSE 5000

# Run the application with gunicorn
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "2", "app:app"]