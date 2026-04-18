FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/cache data/audits logs

EXPOSE 8000

# Bind to localhost only — single-user mode assumes network isolation
# (run behind Tailscale, or expose via docker-compose port mapping).
CMD ["uvicorn", "web.main:app", "--host", "127.0.0.1", "--port", "8000"]
