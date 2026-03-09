FROM python:3.10-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY main_v2.py main.py
COPY dashboard.html .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
