# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for soundfile and other packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libsndfile1 \
    libsndfile-dev \
    build-essential \
    python3-dev \
    pkg-config \
    && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip and setuptools
RUN pip install --upgrade pip setuptools wheel

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Run gunicorn when the container launches
CMD ["sh", "-c", "python -m gunicorn -w 4 --bind 0.0.0.0:8000 app:app"]
