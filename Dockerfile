FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer-cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Create the data directory for the SQLite database
RUN mkdir -p data

CMD ["python", "main.py"]
