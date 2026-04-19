FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY bot/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules + bot code
COPY shared/ ./shared/
COPY wallet/ ./wallet/
COPY bot/ ./bot/

CMD ["python", "-m", "bot.main"]
