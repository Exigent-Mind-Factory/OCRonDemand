#!/usr/bin/env bash

# Step 1: Clean up previous Docker containers and volumes
# docker-compose down -v
# docker system prune -a -f
# docker volume prune -f

# Step 2: Rebuild the Docker images
docker-compose build

# Step 3: Start the Docker containers
docker-compose up #-d

# Step 4: Wait for the database and Redis to be ready
echo "Waiting for the database and Redis to be ready..."
docker-compose exec web ./wait-for-it.sh postgres:5432 --timeout=60 --strict -- echo "Postgres is up"
docker-compose exec web ./wait-for-it.sh redis:6379 --timeout=60 --strict -- echo "Redis is up"

# Step 5: Sleep for a few seconds to ensure all services are fully up
sleep 10  # Increase sleep time to ensure the database is fully ready

# Step 6: Run Alembic migrations to set up the database schema
docker-compose exec web alembic upgrade head

# Step 7: Bring the application up in detached mode
docker-compose up #-d
