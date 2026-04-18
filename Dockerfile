FROM python:3.12-slim

WORKDIR /app

# System deps for cryptography, bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime dirs
RUN mkdir -p data/cache data/users logs

EXPOSE 8000

# Default: run web server
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
