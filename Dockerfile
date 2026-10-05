FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY data_pipeline ./data_pipeline
CMD ["python", "-m", "data_pipeline.etl", "all"]
