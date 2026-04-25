# Pin to a specific Debian base for reproducibility — a bare `python:3.12-slim`
# floats and changed OS patch layers can silently shift TLS roots / glibc /
# CVEs between rebuilds. For the strongest guarantee, replace with a
# @sha256:<digest> pin once you have a known-good build. This tag pin is
# the pragmatic middle ground: stable for most rebuilds, easy to read.
FROM python:3.12.7-slim-bookworm

WORKDIR /app

# Prod install — runtime deps only. Dev tooling (pytest / ruff / pre-commit)
# lives in requirements-dev.txt and is NOT shipped into the image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/cache data/audits logs

EXPOSE 8000

# Bind to localhost only — single-user mode assumes network isolation
# (run behind Tailscale, or expose via docker-compose port mapping).
CMD ["uvicorn", "web.main:app", "--host", "127.0.0.1", "--port", "8000"]
