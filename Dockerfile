FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

COPY . /app

RUN python3 src/modules/generate_reqs.py && \
    if [ -f src/modules/common_requirements.txt ]; then pip install --no-cache-dir -r src/modules/common_requirements.txt; fi && \
    if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi

RUN chmod +x run_for_docker.sh
CMD ["./run_for_docker.sh"]
