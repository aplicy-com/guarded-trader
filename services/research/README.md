# Research harness

Scores pre-registered strategy candidates against Gate 1
([`docs/08-paper-exit-criteria.md`](../../docs/08-paper-exit-criteria.md)) in a throwaway,
network-less container. Decisions: [ADR-0020](../../docs/05-adr/0020-kraken-archive-for-backtest-history.md)
(data), [ADR-0021](../../docs/05-adr/0021-cost-consistent-gate-1-and-random-entry-null.md) (gates).

This code never talks to an exchange: the sandbox has no network, no `.env`, and Freqtrade's
backtester forces dry-run. It is not part of the trading path.

## Layout

| Path | What |
|---|---|
| `candidates.json` | Pre-registered hypotheses and parameters. Committed **before** a candidate runs. |
| `strategies/` | Candidate Freqtrade strategies (research only; never loaded by dry-run/live). |
| `src/research_harness/metrics.py` | Daily mark-to-market equity rebuilt from filled orders; Sharpe, drawdown, fee ratio, trade concentration. |
| `src/research_harness/walkforward.py` | Anchored + rolling window geometry, pooled OOS Sharpe. |
| `src/research_harness/null.py` | Random-entry null (C11): seeded entries at the candidate's rate, same exits. |
| `src/research_harness/dsr.py` | PSR, Deflated Sharpe, minimum track record length. |
| `src/research_harness/registry.py` | Append-only SQLite trial registry (the `N` for DSR). |
| `src/research_harness/ft_runner.py`, `cli.py` | In-process Freqtrade backtests and the run orchestration (sandbox only). |
| `fixtures/kraken-markets.json` | Public Kraken market metadata for the whitelisted pairs, so the sandbox needs no network. |
| `state/registry.sqlite` | The trial registry. Git-ignored; **do not delete it** — deleting it resets N. |
| `runs/<Strategy>.json` | Full result of the latest run of each strategy. Git-ignored. |

## Running

```bash
make kraken-data                      # once per Kraken archive release (~10 GB download)
make research-test                    # unit tests for the pure modules
make research-run STRATEGY=C01Tsmom1d # registers a trial, writes services/research/runs/C01Tsmom1d.json
scripts/research-harness.sh run C01Tsmom1d --seeds 5 --no-register   # harness check, no trial
```

A run of an unchanged candidate (same code, parameters, fee, data snapshot and Freqtrade
version) that already has a result is refused: re-running cannot reset or inflate N. Any change
is a new trial. Use `--no-register` only to check the harness itself, never to look at a
candidate's numbers before registering it.

## What a run does

1. Pre-registers the trial (hypothesis from `candidates.json`).
2. Backtests the canonical timerange at the fee in
   `services/freqtrade/user_data/config.backtest-costs.json`, and again at 2x (reported).
3. Anchored and rolling walk-forward: 12-month IS, 3-month OOS, 15 windows on the canonical range.
4. Random-entry null: 200 seeds, entry rate calibrated to the candidate's trade count, entries
   never placed on a candle where the candidate's own exit fires.
5. Records the result, computes DSR against the registry's N and Sharpe dispersion.
6. Evaluates Gate 1 and writes the JSON report.
