FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY picsift ./picsift
# 运行：docker run --env-file ../.env picsift-worker
CMD ["python", "-m", "picsift", "worker"]
