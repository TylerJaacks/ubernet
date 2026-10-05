FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.* uvicorn==0.32.*
WORKDIR /app
COPY app.py .
ENV DATA_DIR=/data RULES_FILE=/config/rules.json
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
