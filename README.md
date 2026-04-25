# Tennis Arb on Kalshi

Automation for the Kalshi tennis arbitrage strategy:

1. **Predictive model** — surface-aware Elo trained on Jeff Sackmann's ATP/WTA
   match history. Outputs `P(player wins)` → reference fair price for the
   "Yes" contract on each player.
2. **Line monitor** — polls Kalshi's `/events` and `/markets` filtered to the
   `KXATPMATCH` and `KXWTAMATCH` series and emits a "new market" event the
   moment a tennis match goes live.
3. **Trader** — on a new-market event, computes fair (sportsbook anchor first,
   model fallback) and places resting Yes/No bids and exit asks chosen to
   clear a configurable **after-fee** target net per contract. Repeats until
   a configurable cutoff before match start.

**Default mode is PAPER.** Real orders only when `KALSHI_LIVE=true` AND
`--live` is passed on the CLI. Paper bids land in `paper_orders.jsonl`.

---

## Setup

### 1. Kalshi credentials

Kalshi's authenticated API uses **RSA-PSS signatures**, not bearer tokens.
You need two things:

- An **API key id** (a UUID-style string, e.g. `12abc345-...`).
- An **RSA private key file** in PEM format (a text file beginning with
  `-----BEGIN PRIVATE KEY-----`).

How to get them:

1. Log in to your Kalshi account at https://kalshi.com.
2. Open **Profile → API Keys** (or visit `/account/api`).
3. Click **Generate new API key**. Kalshi shows you the **API key id** and
   prompts you to download a `.pem` file containing the private key.
   **Save it once — Kalshi never shows the private key again.**
4. Move the `.pem` somewhere safe outside this repo (the repo `.gitignore`
   excludes `*.pem` but don't take chances). E.g.:
   ```bash
   mkdir -p ~/.config/kalshi
   mv ~/Downloads/kalshi-private-key.pem ~/.config/kalshi/private.pem
   chmod 600 ~/.config/kalshi/private.pem
   ```
5. Copy `.env.example` to `.env` and fill in:
   ```bash
   KALSHI_API_KEY_ID=12abc345-...your-key-id...
   KALSHI_PRIVATE_KEY_PATH=/home/you/.config/kalshi/private.pem
   ```

The PEM file's contents look like:

```
-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ...
...many lines of base64...
...wq1YGJmRmpgGcVBd6P8vGVMOAQ==
-----END PRIVATE KEY-----
```

If yours starts with `-----BEGIN RSA PRIVATE KEY-----` (PKCS#1) the loader
also accepts that format.

### 2. Install + train

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Trains both tours, writes artifacts/elo_atp.json and elo_wta.json.
python -m scripts.train_model --tour atp --years 2018-2024
python -m scripts.train_model --tour wta --years 2018-2024
```

### 3. Optional: sportsbook anchor

The strategy works much better when the model isn't the only price reference.
[the-odds-api.com](https://the-odds-api.com) aggregates real-time h2h odds
from every major US book (DraftKings, FanDuel, BetMGM, Pinnacle, …) into
clean JSON. Free tier: 500 requests/month (fine for testing). Paid: $30/mo
for 20k requests, $59/mo for 100k.

Once you have a key, add it to `.env`:

```bash
ODDS_API_KEY=your-odds-api-key
```

When set, `Trader._fair_price_cents` first asks the-odds-api for the de-vigged
average across books for that match-up. If found, that's the fair price the
optimizer uses. If not (match not in the books yet), it falls back to the Elo
model. This is exactly the strategy you described — bidding below where the
sportsbook line will open — except now we read the sportsbook line directly
instead of guessing it.

### 4. Run

```bash
# Paper mode (default). Watches Kalshi tennis markets and logs the bids it
# *would* have placed. Open paper_orders.jsonl to review.
python -m tennis_arb.main

# Live mode (after you trust paper).
KALSHI_LIVE=true python -m tennis_arb.main --live
```

Kill switch:
```bash
touch .killswitch   # stops new orders on the next loop tick
```

## Strategy and fees

We always place **post-only limit orders**, so we collect Kalshi's lower
**maker** rate, not the taker rate. From Kalshi's Feb 2026 fee schedule:

| | formula | max per contract (at 50¢) |
|---|---|---|
| Taker | `ceil(0.0700 × C × p × (1−p))` | 1.75¢ |
| Maker | `ceil(0.0175 × C × p × (1−p))` | 0.44¢ |

The optimizer (`tennis_arb/strategy.py`) starts at the configured offsets
(`bid_offset_cents`, `ask_offset_cents`) below/above fair, then **widens
until net per contract after both maker fees clears
`target_net_per_contract_cents`** (default 3¢). Whichever side is closer to
50¢ has higher fees, so the optimizer widens the cheaper-fee leg first to
keep fill probability up.

At fair = 50¢, default offsets (4¢ bid / 3¢ ask) give:
- gross = (53 − 46) = 7¢
- maker fee at 46¢ ≈ 0.44¢, at 53¢ ≈ 0.44¢
- net ≈ 6.1¢ per contract

That's a 6× edge on the 1¢ Kalshi tick, before any sportsbook drift.

## Risk

- `max_exposure_per_market: $100`
- `max_contracts_per_side: 200`
- `max_daily_loss: $1000` (trips kill switch)
- `max_global_exposure: $5000`

All checked pre-trade in `risk.py`. The kill switch also trips on the file
flag `.killswitch` and on a loss-cap breach.

## Important: Kalshi tennis void rules

Sportsbooks void bets when a match doesn't complete (retirement, walkover,
suspended). **Kalshi does not.** Kalshi resolves the contract at the
"last-traded fair price" before the disqualifying event, which can be far
from the eventual real outcome and has burned traders for large amounts.

The implication for this strategy: if you have a Yes bid sitting on a thin
book and the named player retires before the line stabilises, you can be
left holding contracts that resolve at a price near your fill rather than
voiding. Mitigations baked into the scaffold:

- `min_fair_price_cents: 15`, `max_fair_price_cents: 85` — skip lopsided
  matches where this risk is largest.
- `cutoff_minutes_before_start: 5` — stop placing new orders close to start,
  when withdrawal news is most likely.
- `max_exposure_per_market: $100` — caps the worst-case bad print.

You should also keep an eye on the Tennis Channel / ATP withdrawal feeds
during operation; a v2 should listen to those automatically.

## Project layout

```
tennis_arb/
  config.py         pydantic config from config.yaml + .env
  fees.py           Kalshi maker/taker fee model
  kalshi_client.py  REST client (RSA-PSS signed)
  kalshi_ws.py      WebSocket client with auto-reconnect
  monitor.py        polls /events + /markets, emits NewMarket events
  model/
    elo.py          surface-aware Elo
    data.py         downloads Sackmann ATP/WTA CSVs
    train.py        train -> artifacts/elo_<tour>.json
    predict.py      load -> P(player wins) -> fair price in cents
  strategy.py       fee-aware bid/ask optimiser
  risk.py           per-market / per-side / global / daily-loss caps
  trader.py         orchestrates fair -> bids -> exit asks -> cutoff
  name_match.py     fuzzy Kalshi-title -> Sackmann-name resolver
  odds_api.py       optional the-odds-api anchor
  store.py          SQLite for known markets + order log + PnL
  main.py           glue: monitor.stream() -> trader.manage_market()
scripts/
  train_model.py
  dry_run.py
tests/              19 passing
```

## Deferred (call out next iteration)

- Subscribe to WS orderbook deltas instead of polling.
- Consume Kalshi fill events and drive `risk.record_fill` in real time.
- Active position flatten at cutoff using marketable orders (currently we
  cancel resting orders but leave residual exposure).
- Empirical fill-probability curve from logged paper-mode data, used to swap
  the deterministic optimiser for an expected-value optimiser.
