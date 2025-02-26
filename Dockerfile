# Use official Python image
FROM python:3.10

# Set the working directory
WORKDIR /app

# Copy the project files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port (not always needed for Telegram bots)
EXPOSE 8080

# Command to run the bot
CMD ["python", "alt-anomalies.py"]
