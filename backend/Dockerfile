FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
ENV TIKTOKEN_CACHE_DIR=/app/token-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
COPY app ./app
COPY evals ./evals
RUN useradd -m -u 10001 idp && mkdir -p /app/data /app/uploads && chown -R idp:idp /app
USER idp
EXPOSE 8000 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
