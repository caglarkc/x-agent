# x-agent

Autonomous, algorithm-aware X account manager described in `PLAN.md`.

## Setup

```bash
cd x-agent
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
cp .env.example .env
```

Fill `.env` with real keys only on your machine. Keep `shadow_mode: true` in
`config/settings.yaml` until you intentionally switch to live posting.

For self-observation, set either:

```yaml
# config/settings.yaml
account:
  x_username: "your_handle"
```

or `X_USERNAME=your_handle` in `.env`.

## P0 Commands

```bash
.venv/bin/python -m src.main db-init
.venv/bin/python -m src.main login
.venv/bin/python -m src.main test-post --text "hello world"
```

With `shadow_mode: true`, `test-post` writes a draft and shadow post audit row
to SQLite and does not call the X API.

## P1 Commands

```bash
.venv/bin/python -m src.main observe-self --username your_handle --limit 10
.venv/bin/python -m src.main observe-trends --limit 20
.venv/bin/python -m src.main observe-niche "AI agents" --limit 20
.venv/bin/python -m src.main observe
```

All browser observation uses the persistent profile in `chrome_profile/`.
