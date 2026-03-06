# Chase point scraper — GUI / Windows branch

This branch adds a **Windows GUI** launcher for the scraper using **tkinter** (no extra dependencies).

## Run the GUI

```bash
python scraper_gui.py
```

- **Account** dropdown: pick one account or **All** (same as options 1–7 or 8 in the CLI).
- **Run scraper**: starts the scraper; log output appears in the window.
- **Continue (after 2FA)**: when Chase shows “Confirm your identity”, complete 2FA in the browser, then click this button (same as pressing Enter in the CLI).
- The browser runs in the background; close it or leave it as you prefer. Data is merged into `output/` as in the CLI.

## Requirements

Same as main branch: `.env` and `config.yaml` (from `.env.example` and `config.example.yaml`).  
`CHASE_HEADED=1` is recommended so you can complete 2FA in the visible browser.

## Notes

- The GUI runs the same `scraper.run_scraper(accounts=...)` as the CLI; only the launcher and output/input are different.
- If you see “Config missing”, copy `config.example.yaml` to `config.yaml` and fill in your accounts.
