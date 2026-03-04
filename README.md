# Severance 💀

**Track what you pay the things replacing you.**

A locally-hosted dashboard for monitoring AI API token spend across providers. See what your AI habit actually costs — broken down by provider, model, and day.

Built for personal use. No telemetry, no cloud, no accounts. Your data stays on your machine.

## Features

- **Multi-provider** — Anthropic + OpenAI out of the box, Google planned
- **Dashboard** — Dark-themed UI with charts and tables, no build step
- **Timeline view** — Daily spend stacked by provider or model
- **Model breakdown** — Per-model token counts, request volumes, and costs
- **Time ranges** — 7d, 14d, 30d, month-to-date, last month, or custom dates
- **Auto-refresh** — Polls provider APIs on a configurable schedule
- **Basic auth** — Password-protected dashboard
- **Offline pricing** — Ships with current model pricing data for cost calculation
- **SQLite storage** — Cached data for fast loading and historical views

## Quick Start

```bash
git clone https://github.com/rdyson/severance.git
cd severance

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp config.example.yaml config.yaml
# Edit config.yaml — add your Admin API keys

severance
```

Open http://127.0.0.1:8077 (default credentials: `admin` / `changeme`).

## Prerequisites

You need **Admin API keys** — these are different from regular API keys:

| Provider | Where to get it | Key format |
|---|---|---|
| **Anthropic** | [console.anthropic.com → Settings → Admin Keys](https://console.anthropic.com/settings/admin-keys) | `sk-ant-admin-...` |
| **OpenAI** | [platform.openai.com → Settings → Organization → Admin Keys](https://platform.openai.com/settings/organization/admin-keys) | `sk-admin-...` |

Both are free to create. They provide read-only access to your usage data.

## Configuration

Copy `config.example.yaml` to `config.yaml`:

```yaml
providers:
  anthropic:
    admin_api_key: "sk-ant-admin-..."
  openai:
    admin_api_key: "sk-admin-..."

auth:
  username: "admin"
  password: "pick-something-better"

server:
  host: "127.0.0.1"
  port: 8077

refresh:
  interval_hours: 6
  default_granularity: "1d"
```

## Usage

```bash
# Start the dashboard
severance

# Custom config path
severance --config /path/to/config.yaml

# Custom host/port
severance --host 0.0.0.0 --port 9090

# Fetch data without starting the server
severance --refresh

# Fetch more history
severance --refresh --days 90

# Debug logging
severance --debug
```

## Docker

```bash
docker build -t severance .

docker run -d \
  -p 8077:8077 \
  -v $(pwd)/config.yaml:/app/config.yaml \
  severance
```

## API Endpoints

All endpoints except `/api/health` require basic auth.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/summary` | Summary totals + previous period comparison |
| `GET` | `/api/usage` | Usage data grouped by provider or model |
| `GET` | `/api/providers` | Per-provider breakdown |
| `GET` | `/api/models` | Per-model breakdown |
| `POST` | `/api/refresh` | Trigger manual data refresh |
| `GET` | `/api/health` | Health check (no auth) |

**Query parameters:** `start`, `end` (ISO 8601), `provider`, `group_by` (`provider` or `model`), `days` (for refresh).

## How It Works

1. **Severance polls** your provider Admin APIs on a schedule (default: every 6 hours)
2. **Normalises** the data — token counts, request volumes, costs
3. **Stores** everything in a local SQLite database
4. **Calculates costs** where providers don't return them directly (Anthropic gives tokens only — Severance multiplies by the model pricing table)
5. **Serves** a dashboard with charts and tables

### Provider Details

| Provider | Token Data | Cost Data | Notes |
|---|---|---|---|
| **Anthropic** | ✅ Via Usage API | 💰 Calculated from pricing | Groups by model. Requires Admin key. |
| **OpenAI** | ✅ Via Usage API | ✅ Via Costs API | Direct dollar amounts. Requires Admin key. |
| **Google** | 🔜 Planned | 🔜 Planned | No equivalent usage API yet. |

### Pricing Data

Severance ships with a `pricing/models.json` file containing per-model token prices. This is used to calculate costs for providers that only return token counts (currently Anthropic).

If prices change, update `severance/pricing/models.json` and restart. PRs welcome to keep this current.

## Project Structure

```
severance/
├── config.example.yaml       # Example config
├── severance/
│   ├── __main__.py           # CLI entry point
│   ├── server.py             # FastAPI app + REST endpoints
│   ├── config.py             # YAML config loading
│   ├── db.py                 # SQLite schema + queries
│   ├── auth.py               # Basic auth middleware
│   ├── scheduler.py          # Background refresh + cost calculation
│   └── providers/
│       ├── base.py           # Abstract provider interface
│       ├── anthropic_provider.py
│       └── openai_provider.py
├── static/
│   ├── index.html            # Dashboard (single page)
│   ├── app.js                # Charts + API calls (vanilla JS)
│   └── style.css             # Dark theme
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Adding a Provider

Implement `BaseProvider` in `severance/providers/`:

```python
from severance.providers.base import BaseProvider, UsageRecord

class MyProvider(BaseProvider):
    name = "myprovider"

    async def is_configured(self) -> bool:
        return bool(self.api_key)

    async def fetch_usage(self, start, end, granularity="1d") -> list[UsageRecord]:
        # Fetch and return normalised records
        ...
```

Then register it in `scheduler.py`. Add pricing data to `models.json` if needed.

## License

MIT
