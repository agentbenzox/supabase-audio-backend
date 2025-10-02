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

# Create a non-root user for security
RUN useradd -m appuser

# Switch to the non-root user
USER appuser

# Make port 8000 available to the world outside this container
EXPOSE 8000

# CRITICAL FIX: Run Gunicorn via the Python interpreter for reliability.
# We explicitly call the shell to run the python command as a module.
CMD ["sh", "-c", "python -m gunicorn -w 4 --bind 0.0.0.0:8000 app:app"]
