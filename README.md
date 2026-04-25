# Tennis Arb on Kalshi

Automation for the Kalshi tennis arbitrage strategy:

1. **Predictive model** — surface-aware Elo trained on Jeff Sackmann's ATP/WTA
   match history. Outputs `P(player wins)`, used as the reference fair price
   when sportsbook lines aren't available yet.
2. **Line monitor** — polls Kalshi `/events` and `/markets` filtered to tennis
   series, plus a WebSocket orderbook subscription, and emits a "new market"
   event the moment a tennis match goes live.
3. **Trader** — on a new-market event, reads the model fair price (and optional
   live sportsbook price), places resting Yes/No bids below fair, then flips
   them to asks above fair as the orderbook stabilises. Repeats until match
   start (configurable cutoff).

**Default mode is PAPER.** Real orders are only placed when
`KALSHI_LIVE=true` AND `--live` is passed on the CLI. Don't change this until
you've watched it run on paper for a session.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Train the model (downloads ~30 MB of CSVs from Sackmann's repo).
python -m scripts.train_model --tour atp --years 2015-2024
python -m scripts.train_model --tour wta --years 2015-2024

# 2. Configure credentials (copy and fill in).
cp .env.example .env
# Put your Kalshi RSA private key at the path referenced in .env.

# 3. Dry run — connects to Kalshi, watches tennis markets, logs the bids it
#    *would* place. Does NOT submit orders.
python -m tennis_arb.main

# 4. Go live (after you trust the dry-run output).
KALSHI_LIVE=true python -m tennis_arb.main --live
```

## Configuration

Edit `config.yaml` for strategy parameters. Key knobs:

- `edge_cents` — minimum edge vs. fair price required to place a bid (default 4)
- `max_exposure_per_market` — max $ at risk on any single match (default 50)
- `max_daily_loss` — global kill switch (default 500)
- `cutoff_minutes_before_start` — stop trading N minutes before match (default 5)
- `poll_interval_seconds` — how often to scan for new tennis markets (default 2)

## Project layout

```
tennis_arb/
  config.py             # Pydantic config loader
  kalshi_client.py      # REST client (RSA-PSS signed)
  kalshi_ws.py          # WebSocket client
  model/
    elo.py              # Surface-aware Elo
    data.py             # Sackmann CSV loader
    train.py            # Training loop
    predict.py          # Inference: P(player wins)
  monitor.py            # Detect new tennis markets
  strategy.py           # Decide bid/ask prices
  risk.py               # Exposure caps, kill switch
  trader.py             # Order lifecycle
  name_match.py         # Kalshi name -> Sackmann name
  odds_api.py           # Optional: the-odds-api anchor
  store.py              # SQLite state
  main.py               # Orchestrator
scripts/
  train_model.py
  dry_run.py
tests/
  ...
```

## Risk and safety

- Hard exposure caps in `risk.py`. Trips kill the trader for the day.
- Kill switch: `touch .killswitch` in the project root halts new orders and
  begins flattening open positions on the next loop iteration.
- All orders are tagged with a client order id so we can reconcile after a
  restart.
- Paper mode logs the full intended order to `paper_orders.jsonl`.

## Open questions / TODOs

See the conversation that produced this scaffold. Top items:

- Confirm Kalshi tennis series tickers in `config.yaml` (placeholder values).
- Tune `edge_cents` and exposure caps to your bankroll.
- Add a sportsbook anchor (the-odds-api or Pinnacle) — strongly recommended,
  since the sportsbook line IS the thing the market converges to.
- Consider Glicko-2 over Elo for tighter rating intervals on low-volume players.
