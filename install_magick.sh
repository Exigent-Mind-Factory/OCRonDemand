#!/usr/bin/env bash

echo "Starting ImageMagick installation in the ocrondemand-celery-1 container..."

# Step 1: Ensure the container is running
container_name="ocrondemand-celery-1"
if [ ! "$(docker ps -q -f name=$container_name)" ]; then
    echo "Error: $container_name is not running. Please start the container first."
    exit 1
fi

# Step 2: Remove any existing ImageMagick directory and ensure it's deleted
echo "Removing any existing ImageMagick directory..."
docker exec $container_name bash -c "
    rm -rf /app/ImageMagick /app/ImageMagick-7.1.1-37 /app/ImageMagick.tar.gz &&
    echo 'ImageMagick directory cleared.'"

# Step 3: Install dependencies
echo "Installing dependencies..."
docker exec $container_name bash -c "
    apt-get update &&
    apt-get install -y build-essential libjpeg-dev libpng-dev libtiff-dev libfreetype6-dev pkg-config git wget &&
    echo 'Dependencies installed.'"

# Step 4: Download ImageMagick source tarball
echo "Downloading ImageMagick source..."
docker exec $container_name bash -c "
    cd /app &&
    wget https://imagemagick.org/download/releases/ImageMagick-7.1.1-37.tar.gz &&
    tar xvzf ImageMagick-7.1.1-37.tar.gz &&
    cd ImageMagick-7.1.1-37 &&
    echo 'ImageMagick source downloaded and extracted.'"

# Step 5: Configure, compile, and install ImageMagick
echo "Configuring, compiling, and installing ImageMagick..."
docker exec $container_name bash -c "
    cd /app/ImageMagick-7.1.1-37 &&
    ./configure &&
    make -j$(nproc) &&
    make install &&
    echo 'ImageMagick installed successfully.'"

# Step 6: Update the shared library cache
echo "Updating the shared library cache..."
docker exec $container_name bash -c "
    ldconfig /usr/local/lib &&
    echo 'Shared library cache updated.'"

# Step 7: Verify the installation
echo "Verifying ImageMagick installation..."
docker exec $container_name bash -c "
    if command -v magick >/dev/null 2>&1; then
        magick --version
    else
        echo 'Error: ImageMagick installation failed.'
    fi"

echo "ImageMagick installation completed."
