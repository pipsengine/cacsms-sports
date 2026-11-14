FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && python -m playwright install --with-deps chromium
COPY apps/api/ /app/
COPY engines/ /app/engines/
ENV PYTHONPATH=/app
RUN mkdir -p /var/lib/cacsms/evidence
CMD ["sh","-c","alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
