FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY severance/ severance/
COPY static/ static/

RUN pip install --no-cache-dir .

EXPOSE 8077

# Default: run the server
# Mount your config.yaml at /app/config.yaml
CMD ["severance", "--host", "0.0.0.0"]
