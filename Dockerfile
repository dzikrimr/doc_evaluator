# Gunakan Python 3.11 slim
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy semua kode dan model
COPY . .

# Set environment variable default (bisa override saat docker run)
ENV SENDGRID_API_KEY=""

# Jalankan worker saat container start
CMD ["python", "worker_local.py"]
