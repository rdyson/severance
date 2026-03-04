# Severance — Project Plan

**Track what you pay the things replacing you.**

A locally-hosted dashboard for monitoring AI API token spend across providers. Designed for personal/small-team use, packaged for easy sharing on GitHub.

**Repo:** https://github.com/rdyson/severance

---

## Decisions

| Decision | Choice |
|---|---|
| Name | `severance` |
| Providers v1 | Anthropic (full) + OpenAI (full) + Google (best-effort / v1.1) |
| Auth | Basic auth from config |
| Alerts | Visual only for v1 |
| Frontend | Static HTML + Chart.js, no build step |
| Backend | Python + FastAPI |
| Storage | SQLite (cached usage data) |
| Packaging | pip install + Docker |

---

## Architecture

```
severance/
├── config.example.yaml       # Example config (committed)
├── config.yaml               # User config (gitignored)
├── severance/
│   ├── __init__.py
│   ├── __main__.py           # Entry point: python -m severance
│   ├── server.py             # FastAPI app
│   ├── auth.py               # Basic auth middleware
│   ├── db.py                 # SQLite setup + queries
│   ├── scheduler.py          # Background refresh scheduling
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py           # Abstract provider interface
│   │   ├── anthropic_provider.py   # Anthropic Usage API
│   │   └── openai_provider.py      # OpenAI Usage + Costs API
│   └── pricing/
│       └── models.json       # Per-model token pricing
├── static/
│   ├── index.html            # Single-page dashboard
│   ├── app.js                # Chart rendering + API calls
│   └── style.css
├── Dockerfile
├── pyproject.toml
├── README.md
├── LICENSE
└── PLAN.md
```

---

## Provider API Details

### Anthropic
- **Endpoint:** `GET /v1/organizations/usage_report/messages`
- **Auth:** Admin API key (`sk-ant-admin-...`) — different from regular key
- **Granularity:** `1m`, `1h`, `1d` buckets
- **Group by:** model, workspace, API key, service tier
- **Returns:** Token counts (input, output, cached input, cache creation)
- **Costs:** Not returned — must calculate from tokens × model pricing
- **Docs:** https://docs.anthropic.com/en/api/usage-cost-api

### OpenAI
- **Usage endpoint:** `GET /v1/organization/usage/completions`
- **Costs endpoint:** `GET /v1/organization/costs`
- **Auth:** Admin API key (from platform.openai.com/settings/organization/admin-keys)
- **Granularity:** `1m`, `1h`, `1d` buckets
- **Group by:** model, project, user, API key
- **Returns:** Token counts + direct dollar costs (from Costs endpoint)
- **Docs:** https://platform.openai.com/docs/api-reference/usage

### Google (best-effort)
- **No equivalent usage API** — Google AI Studio has no programmatic usage endpoint
- **Cloud Billing API:** Project-level daily costs, not per-model token breakdown
- **BigQuery export:** Granular but requires BigQuery setup (overkill for personal)
- **Plan:** Support via Cloud Billing API for daily cost totals, or CSV import. Add proper support when Google ships a usage API.

---

## Data Model

### Normalised usage record (SQLite)

```sql
CREATE TABLE usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,          -- "anthropic" | "openai" | "google"
    model TEXT,                      -- "claude-sonnet-4-6" | "gpt-4o" | null
    timestamp TEXT NOT NULL,         -- ISO 8601, bucket start time
    granularity TEXT NOT NULL,       -- "1m" | "1h" | "1d"
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    requests INTEGER DEFAULT 0,
    cost_usd REAL,                   -- from API or calculated
    raw_json TEXT,                   -- original API response for debugging
    fetched_at TEXT NOT NULL,        -- when we pulled this data
    UNIQUE(provider, model, timestamp, granularity)
);
```

### Pricing table

```sql
CREATE TABLE pricing (
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_per_mtok REAL NOT NULL,    -- $ per 1M input tokens
    output_per_mtok REAL NOT NULL,   -- $ per 1M output tokens
    cached_per_mtok REAL,            -- $ per 1M cached tokens (if applicable)
    effective_from TEXT NOT NULL,     -- ISO 8601 date
    PRIMARY KEY(provider, model, effective_from)
);
```

---

## Dashboard Views

1. **Overview card** — Total spend this month (all providers), delta vs last month
2. **Timeline chart** — Daily spend stacked by provider or model, selectable range
3. **Provider breakdown** — Side-by-side cards with pie chart
4. **Model breakdown table** — Per-model: tokens in/out, cached, cost, request count
5. **Time range picker** — This month / Last 7d / Last 30d / Custom range

---

## Config

```yaml
# config.example.yaml
providers:
  anthropic:
    admin_api_key: "sk-ant-admin-..."
  openai:
    admin_api_key: "sk-admin-..."
  # google:
  #   project_id: "my-project"
  #   credentials_path: "/path/to/service-account.json"

auth:
  username: "admin"
  password: "changeme"

server:
  host: "127.0.0.1"
  port: 8077

refresh:
  interval_hours: 6        # How often to poll provider APIs
  default_granularity: "1d"
```

---

## Prerequisites

Before using Severance, you need:
- [ ] Anthropic Admin API key (console.anthropic.com → Settings → Admin Keys)
- [ ] OpenAI Admin API key (platform.openai.com → Settings → Organization → Admin Keys)
- [ ] Python 3.11+

---

## Build Phases

### Phase 1: Core backend
- [x] Project scaffolding (pyproject.toml, directory structure)
- [x] Config loading (YAML)
- [x] SQLite schema + db.py
- [x] Provider base class
- [x] Anthropic provider (fetch + normalise + cost calculation)
- [x] OpenAI provider (fetch usage + fetch costs + normalise)
- [x] Pricing data (models.json with current Anthropic + OpenAI prices)
- [x] FastAPI server with REST endpoints
- [x] Basic auth middleware
- [x] Background scheduler for auto-refresh

### Phase 2: Frontend
- [x] index.html layout (header, cards, charts, table)
- [x] Chart.js integration
- [x] Overview card (total spend + delta vs previous period)
- [x] Timeline chart (daily spend, stacked bar, by provider/model toggle)
- [x] Provider breakdown (doughnut chart)
- [x] Model breakdown table (provider badge, tokens, requests, cost)
- [x] Time range picker (7d, 14d, 30d, MTD, Last Month, custom dates)
- [x] Responsive styling (dark theme, mobile-friendly)

### Phase 3: Packaging & docs
- [x] README.md (setup, config, provider details, API docs, project structure)
- [x] config.example.yaml
- [x] Dockerfile + .dockerignore
- [x] pyproject.toml (pip installable, `severance` CLI entry point)
- [x] LICENSE (MIT)
- [x] Git repo initialised, initial commit
- [ ] Push to GitHub (needs `gh` CLI or manual remote add)

### Phase 4: Google support (v1.1)
- [ ] Google Cloud Billing provider
- [ ] CSV import fallback
- [ ] Docs for Google setup

---

## Open Questions (to resolve during build)

- Pricing data maintenance: ship static JSON and let users PR updates? Or fetch from a community-maintained source?
- Chart style: dark mode? Light mode? Follow system preference?
- Mobile: worth optimising for phone viewing, or desktop-only for v1?

---

## Links

- Anthropic Usage API: https://docs.anthropic.com/en/api/usage-cost-api
- OpenAI Usage API: https://platform.openai.com/docs/api-reference/usage
- OpenAI Cookbook (usage example): https://cookbook.openai.com/examples/completions_usage_api
- Chart.js: https://www.chartjs.org/
- FastAPI: https://fastapi.tiangolo.com/
