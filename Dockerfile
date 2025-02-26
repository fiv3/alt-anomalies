# Use an official lightweight Python image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

# Copy only necessary files first for efficient caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose port for Fly.io health checks
EXPOSE 8080

# Start the bot
CMD ["python", "alt-anomalies.py"]
