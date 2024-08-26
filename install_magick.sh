#!/usr/bin/env bash

# Ensure the container is running
docker exec ocrondemand-celery-1 bash -c "
    apt-get update &&
    apt-get remove -y imagemagick &&
    apt-get install -y build-essential libjpeg-dev libpng-dev libtiff-dev libfreetype6-dev pkg-config git &&
    
    # Remove any existing ImageMagick directory if present
    rm -rf ImageMagick &&
    
    # Increase buffer size for git clone
    git config --global http.postBuffer 104857600 &&  # Set buffer to 100MB
    
    # Clone the repository with retries
    for i in {1..5}; do
        git clone https://github.com/ImageMagick/ImageMagick.git && break || sleep 5;
    done &&
    
    cd ImageMagick &&
    git checkout 7.1.1-37 &&
    
    # Configure, make, and install
    ./configure &&
    make &&
    make install &&
    
    # Configure the system
    ldconfig /usr/local/lib &&
    
    # Verify installation
    magick --version
"
