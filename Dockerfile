# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Install necessary packages, including ImageMagick, `tesseract-ocr`, `ocrmypdf`, and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    coreutils \
    tesseract-ocr \
    libtesseract-dev \
    ocrmypdf \
    poppler-utils \
    ghostscript \
    libxml2 \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpq-dev \
    imagemagick \
    libmagickwand-dev \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed Python packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Verify that alembic is installed
RUN alembic --help || (echo "Alembic not found!" && exit 1)

# Make port 8778 available to the world outside this container
EXPOSE 8778

# Define environment variable
ENV PYTHONUNBUFFERED=1

# Run the application when the container launches
CMD ["python", "run.py"]
