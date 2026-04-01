# Chase point scraper

Automates logging into Chase Ultimate Rewards, selecting an account, and scraping points activity into CSV/Excel. Supports multiple accounts, shared 2FA profiles, and merging only new transactions into per-account files.

**Security:** No account numbers, usernames, or passwords are stored in this repo. You provide them via `.env` and `config.yaml` (from the templates below).

## Requirements

- Python 3.8+
- Chrome (for Playwright)
- Chase Ultimate Rewards accounts

## Setup

1. **Clone and install**
   ```bash
   git clone https://github.com/YOUR_USERNAME/chase-point-scraper.git
   cd chase-point-scraper
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Config (no secrets in repo)**
   - Copy `config.example.yaml` → `config.yaml`
   - Edit `config.yaml`: set your account names, last-4 digits for each card, and which env vars to use for credentials. Do not commit `config.yaml`.

3. **Credentials (never commit)**
   - Copy `.env.example` → `.env`
   - Edit `.env`: set the `CHASE_USER_*` and `CHASE_PASSWORD_*` values for each credential group. Do not commit `.env`.

4. **Optional:** Set `CHASE_HEADED=1` in `.env` to run the browser visible (needed for 2FA the first time per profile group).

## Usage

```bash
python scraper.py
```

- Choose an account (1–7) or **All** to run each account in succession.
- On first run (or when Chase asks), complete 2FA in the browser; the script pauses for you.
- The scraper signs out after each run. Data is merged into one file per account under `output/` (CSV/Excel as configured).

### Points balance over time

Each successful run appends one row to **`output/balance_history.xlsx`** (sheet **Balance history**), or **`balance_history.csv`** if Excel isn’t available:

| Snapshot At        | Account Name | Points Balance |
|--------------------|--------------|----------------|
| 2026-03-05T14:32:01 | Sapphire Pref | 125430 |

All accounts share this file so you can **filter by Account Name** or build a simple chart in Excel. Turn off with `record_balance_each_run: false` in `config.yaml`. If the balance is wrong or missing, set **`selectors.points_balance`** in `config.yaml` to a CSS selector that wraps your total points (inspect the rewards page in DevTools).

## What’s in the repo (templates only)

| File                | Purpose |
|---------------------|--------|
| `config.example.yaml` | Template for account names, last-4 digits, and env var mapping. Copy to `config.yaml`. |
| `.env.example`      | Template for credential env vars. Copy to `.env`. |
| `scraper.py`        | Main script. |
| `requirements.txt`  | Python dependencies. |

**Not in the repo (in `.gitignore`):** `.env`, `config.yaml`, `output/`, `session/`, and any `*.xlsx`/`*.csv` so logins and scraped data stay local.

## License

Use at your own risk. Not affiliated with Chase.

---

## Publish to GitHub

1. Create a new repository on GitHub named **chase-point-scraper** (or similar). Do not add a README or .gitignore there.
2. In this folder:
   ```bash
   git init
   git add .gitignore .env.example config.example.yaml README.md requirements.txt scraper.py
   git commit -m "Initial commit: Chase point scraper (templates only, no credentials)"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/chase-point-scraper.git
   git push -u origin main
   ```
3. Confirm `.env` and `config.yaml` are **not** in the commit (`git status` should not list them; they are in `.gitignore`).
