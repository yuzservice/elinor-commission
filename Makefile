.PHONY: up dev down logs seed test migrate backup restore
up:
	docker compose up -d --build
dev:
	docker compose -f compose.yaml -f compose.dev.yaml up --build
down:
	docker compose down
logs:
	docker compose logs -f web
seed:
	docker compose exec web python manage.py seed
test:
	docker compose exec web python manage.py test
migrate:
	docker compose exec web python manage.py migrate
backup:
	./scripts/backup.sh
restore:
	./scripts/restore.sh $(FILE)

