COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml

.PHONY: up down logs download-data backtest shell market-facts \
	vps-plan vps-apply vps-lockdown verify-lockdown ssh \
	conductor-test conductor-lint conductor-shell push-env deploy-files deploy logs-remote

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
		/repo/scripts/fetch_ohlcv.py --venue kraken

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

# --- Conductor (work package 3A-1) ---------------------------------------------
CONDUCTOR := cd services/conductor &&

conductor-test:
	$(CONDUCTOR) uv run pytest

conductor-lint:
	$(CONDUCTOR) uv run ruff check . && uv run ruff format --check . \
		&& uv run mypy --strict src/conductor/domain && uv run mypy

# Shell inside the built image (as the non-root user, read-only like prod).
conductor-shell:
	$(COMPOSE) run --rm --no-deps --entrypoint sh conductor

# --- VPS (work package 3A-0; see docs/06-runbooks/provision-vps.md) ---------
# Secrets come ONLY from the environment: TF_VAR_hcloud_token and
# TF_VAR_tailscale_authkey. Nothing here writes them to a file.
TF         := terraform -chdir=infra/terraform
VPS_HOST   ?= ai-trader-vps
VPS_USER   ?= deploy
VPS_DIR    ?= /opt/ai-trading-agent
SSH_KEY    ?= $(HOME)/.ssh/ai_trader_vps
SSH_OPTS   := -i $(SSH_KEY) -o IdentitiesOnly=yes
# Runtime state that lives on the VPS only; deploy must never overwrite or
# delete it (rsync excludes also protect from --delete).
RSYNC_KEEP := --exclude=/.env \
	--exclude=/services/freqtrade/user_data/data/ \
	--exclude=/services/freqtrade/user_data/logs/ \
	--exclude=/services/freqtrade/user_data/backtest_results/ \
	--exclude='*.sqlite' --exclude='*.sqlite-shm' --exclude='*.sqlite-wal' \
	--exclude=/services/conductor/data/ --exclude='/services/conductor/*.db'

define require_tf_env
	@test -n "$$TF_VAR_hcloud_token" || { echo "TF_VAR_hcloud_token is not set (see provision-vps.md)"; exit 1; }
	@test -n "$$TF_VAR_tailscale_authkey" || { echo "TF_VAR_tailscale_authkey is not set (see provision-vps.md)"; exit 1; }
endef

# BOOTSTRAP=true previews the first provision; BOOTSTRAP=false previews lockdown.
BOOTSTRAP ?= true

vps-plan:
	$(require_tf_env)
	$(TF) init -input=false
	$(TF) plan -input=false -var bootstrap_ssh=$(BOOTSTRAP)

# First provision ONLY: opens SSH from admin_cidr. Prompts for confirmation.
vps-apply:
	$(require_tf_env)
	$(TF) init -input=false
	$(TF) apply -var bootstrap_ssh=true

# Steady state: removes the SSH rule, leaving zero public inbound. Also the
# command for any later infra change, so a stray apply can't re-open SSH.
vps-lockdown:
	$(require_tf_env)
	$(TF) init -input=false
	$(TF) apply -var bootstrap_ssh=false

# Fails (exit 1) if any of TCP 22 (ssh), 443 (tailscale serve), 8000 (dashboard) or 8080
# (Freqtrade API) on the public IP accepts a connection. Run after every lockdown and after
# every deploy that touches published ports. Needs a network where those outbound ports are
# not themselves blocked, and no Tailscale exit node (check `tailscale status`).
verify-lockdown:
	@ip=$$($(TF) output -raw ipv4) && test -n "$$ip" || { echo "cannot read ipv4 from terraform output"; exit 2; }; \
	bad=0; for port in 22 443 8000 8080; do \
		if nc -z -G 8 "$$ip" $$port 2>/dev/null; then \
			echo "FAIL: TCP $$port on $$ip ACCEPTS connections - lockdown is NOT effective"; bad=1; \
		else echo "OK: TCP $$port on $$ip does not accept connections"; fi; \
	done; exit $$bad

# Over the tailnet by default. Before lockdown/Tailscale is up, use the public
# IP:  make ssh VPS_HOST=$$(terraform -chdir=infra/terraform output -raw ipv4)
ssh:
	ssh $(SSH_OPTS) $(VPS_USER)@$(VPS_HOST)

# Copy local .env to the VPS as root:deploy 0640 (never via a world-readable
# temp file). Refuses a non-dry-run .env unless ALLOW_LIVE_ENV=1.
push-env:
	@test -f .env || { echo ".env not found in repo root"; exit 1; }
	@grep -q '^TRADING_MODE=dry_run[[:space:]]*$$' .env || [ "$$ALLOW_LIVE_ENV" = "1" ] || \
		{ echo "Refusing: .env does not set TRADING_MODE=dry_run (override: ALLOW_LIVE_ENV=1)"; exit 1; }
	ssh $(SSH_OPTS) $(VPS_USER)@$(VPS_HOST) 'umask 077 && cat > $(VPS_DIR)/.env.incoming \
		&& sudo chown root:deploy $(VPS_DIR)/.env.incoming \
		&& sudo chmod 0640 $(VPS_DIR)/.env.incoming \
		&& sudo mv -f $(VPS_DIR)/.env.incoming $(VPS_DIR)/.env' < .env
	@echo "pushed .env -> $(VPS_HOST):$(VPS_DIR)/.env (root:deploy 0640)"

# Copy the committed state of main (not the working tree) to the VPS WITHOUT starting
# anything. Used by rebuild-vps.md to restore data before the first start.
deploy-files:
	@tmp=$$(mktemp -d) && trap 'rm -rf "$$tmp"' EXIT && \
		git archive main | tar -x -C "$$tmp" && \
		rsync -az --delete $(RSYNC_KEEP) -e "ssh $(SSH_OPTS)" "$$tmp"/ $(VPS_USER)@$(VPS_HOST):$(VPS_DIR)/

# Deploy the committed state of main and start it.
deploy: deploy-files
	ssh $(SSH_OPTS) $(VPS_USER)@$(VPS_HOST) 'cd $(VPS_DIR) && docker compose --env-file .env -f infra/docker-compose.yml up -d --build'

logs-remote:
	ssh -t $(SSH_OPTS) $(VPS_USER)@$(VPS_HOST) 'cd $(VPS_DIR) && docker compose --env-file .env -f infra/docker-compose.yml logs -f --tail 200 freqtrade'
