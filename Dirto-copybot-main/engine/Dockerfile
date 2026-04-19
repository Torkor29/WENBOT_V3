FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules + engine code
COPY shared/ ./shared/
COPY wallet/ ./wallet/
COPY engine/ ./engine/

CMD ["python", "-m", "engine.main"]
