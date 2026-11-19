.PHONY: setup lab-images up down logs ps test frontend-build config

setup:
	python3 scripts/setup.py

lab-images:
	docker build -t netlab/ubuntu-lab:24.04 images/ubuntu-lab
	docker build -t netlab/debian-lab:bookworm images/debian-lab
	docker build -t netlab/debian-router:bookworm images/debian-router

up: setup lab-images
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

test:
	@if [ -x .venv/bin/python ]; then .venv/bin/python -m unittest discover -v; else python3 -m unittest discover -v; fi

frontend-build:
	cd frontend && npm ci && npm run build

config:
	docker compose config
