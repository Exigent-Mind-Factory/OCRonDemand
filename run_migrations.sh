#!/usr/bin/env bash

docker-compose exec web alembic revision --autogenerate -m "Made new revision"
docker-compose exec web alembic upgrade head