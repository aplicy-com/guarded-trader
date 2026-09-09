COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down logs download-data backtest shell

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail 200 freqtrade

download-data:
	$(COMPOSE) run --rm freqtrade download-data \
		--config user_data/config.dry_run.json \
		--timeframes 4h 1d \
		--days 730

backtest:
	$(COMPOSE) run --rm freqtrade backtesting \
		--config user_data/config.dry_run.json \
		--strategy Baseline4h

shell:
	$(COMPOSE) run --rm --entrypoint bash freqtrade
