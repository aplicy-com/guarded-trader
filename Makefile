COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: up down logs download-data backtest shell market-facts

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail 200 freqtrade

download-data:
	# Freqtrade's own `download-data` refuses to run for Kraken (its public
	# OHLC endpoint doesn't serve historic klines — see
	# docs/research/03-baseline-backtest.md "Data" section). This pulls the
	# maximum real history Kraken's API actually serves via ccxt directly,
	# through Freqtrade's own data handler.
	$(COMPOSE) run --rm -v $(CURDIR):/repo --entrypoint python freqtrade \
		/repo/scripts/fetch_kraken_ohlcv.py

backtest:
	$(COMPOSE) run --rm freqtrade backtesting \
		--config user_data/config.dry_run.json \
		--strategy Baseline4h \
		--fee 0.0036 \
		--enable-protections

shell:
	$(COMPOSE) run --rm --entrypoint bash freqtrade

market-facts:
	$(COMPOSE) run --rm -v $(CURDIR):/repo --entrypoint python freqtrade \
		/repo/scripts/kraken_market_facts.py \
		--out /repo/docs/research/02-kraken-market-facts.md
