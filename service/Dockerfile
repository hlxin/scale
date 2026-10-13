# The SCALE web service (service/README.md). Build from the repository root:
#   docker build -f service/Dockerfile -t scale-web .
# The image holds the repository (the schema, the skills, the public example) and runs scale-catal from it.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir ".[pdf,search]" -r service/requirements.txt

ENV PYTHONPATH=/app/service \
    SCALE_NO_UPDATE_CHECK=1 \
    SCALE_WEB_WORKDIR=/tmp/scale-web
RUN useradd --create-home scale && mkdir -p /tmp/scale-web && chown scale /tmp/scale-web
USER scale
EXPOSE 8080
CMD ["python", "-m", "scaleweb", "--port", "8080"]
