# WenBot — Commands rapides
# =========================

NS = wenbot-prod

# ── Build ───────────────────────────────────────────────────────────
.PHONY: build build-engine build-bot build-strategy

build: build-engine build-bot build-strategy

build-engine:
	docker build -f engine/Dockerfile -t wenbot/engine:latest .

build-bot:
	docker build -f bot/Dockerfile -t wenbot/bot:latest .

build-strategy:
	docker build -f strategies/example_strategy/Dockerfile -t wenbot/strategy-test:latest .

# ── Deploy ──────────────────────────────────────────────────────────
.PHONY: deploy deploy-engine deploy-bot deploy-redis

deploy: deploy-redis deploy-engine deploy-bot
	@echo "All deployed. Run: make status"

deploy-redis:
	kubectl apply -f k8s/redis.yaml

deploy-engine: build-engine
	kubectl apply -f k8s/execution-engine.yaml
	kubectl -n $(NS) rollout restart deployment/execution-engine

deploy-bot: build-bot
	kubectl apply -f k8s/telegram-bot.yaml
	kubectl -n $(NS) rollout restart deployment/telegram-bot

# ── Status ──────────────────────────────────────────────────────────
.PHONY: status pods logs-engine logs-bot logs-redis

status:
	@echo "── $(NS) ──"
	@kubectl -n $(NS) get pods -o wide
	@echo ""
	@echo "── portainer ──"
	@kubectl -n portainer get pods -o wide

pods:
	kubectl -n $(NS) get pods

logs-engine:
	kubectl -n $(NS) logs -f deployment/execution-engine --tail=100

logs-bot:
	kubectl -n $(NS) logs -f deployment/telegram-bot --tail=100

logs-redis:
	kubectl -n $(NS) logs -f statefulset/redis --tail=50

# ── Restart ─────────────────────────────────────────────────────────
.PHONY: restart-engine restart-bot restart-all

restart-engine:
	kubectl -n $(NS) rollout restart deployment/execution-engine

restart-bot:
	kubectl -n $(NS) rollout restart deployment/telegram-bot

restart-all: restart-engine restart-bot

# ── Test strategy ───────────────────────────────────────────────────
.PHONY: test-strategy

test-strategy:
	python3 scripts/test_strategy.py

# ── Tests ───────────────────────────────────────────────────────────
.PHONY: test

test:
	python3 -m pytest tests/ -v

# ── Infra setup (run as root) ──────────────────────────────────────
.PHONY: setup

setup:
	sudo bash scripts/setup_infra.sh
