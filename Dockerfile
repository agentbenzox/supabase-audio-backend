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
    python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8000 available to the world outside this container
EXPOSE 8000

# Fix: We use the explicit path to the installed gunicorn executable within the container's virtual environment setup.
# This path is where pip installs executables for the system Python.
CMD ["/usr/local/bin/gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
