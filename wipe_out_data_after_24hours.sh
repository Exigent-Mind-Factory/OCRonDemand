#!/bin/bash

# Set the directories to clean
UPLOADS_DIR="./uploads"
OCR_OUTPUT_DIR="./ocr_output"

# Log the current files before attempting to delete
echo "Files before deletion:" >> ./cleanup.log
find "$UPLOADS_DIR" -mindepth 1 >> ./cleanup.log
find "$OCR_OUTPUT_DIR" -mindepth 1 >> ./cleanup.log

# Try deleting all files and folders inside the specified directories
find "$UPLOADS_DIR" -mindepth 1 -exec rm -rf {} \; >> ./cleanup.log 2>&1
find "$OCR_OUTPUT_DIR" -mindepth 1 -exec rm -rf {} \; >> ./cleanup.log 2>&1

# Log the cleanup action and check if any files remain
echo "Files after deletion:" >> ./cleanup.log
find "$UPLOADS_DIR" -mindepth 1 >> ./cleanup.log
find "$OCR_OUTPUT_DIR" -mindepth 1 >> ./cleanup.log

echo "Cleanup script executed at $(date)" >> ./cleanup.log
