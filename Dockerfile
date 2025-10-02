# Use an official Python runtime as a parent image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Install system dependencies required for soundfile and other packages
# We keep these dependencies because they are necessary for your backend's libraries
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

# Fix: Use the absolute path to the Python interpreter to run the gunicorn module directly.
# This bypasses any PATH environment issues caused by the hosting platform (Render).
# The gunicorn executable is resolved by Python's module system.
CMD ["/usr/local/bin/python", "-m", "gunicorn", "--bind", "0.0.0.0:8000", "app:app"]
