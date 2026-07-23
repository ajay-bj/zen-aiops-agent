FROM python:3.12-slim

RUN groupadd -r pharma && useradd -r -g pharma -d /app -s /sbin/nologin pharma

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

USER pharma

EXPOSE 8000

CMD ["python", "-m", "src.main"]
