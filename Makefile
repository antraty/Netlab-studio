.PHONY: up down logs ps test frontend-build config

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

test:
	python3 -m unittest discover -v

frontend-build:
	cd frontend && npm ci && npm run build

config:
	docker compose config
