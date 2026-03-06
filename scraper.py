"""
Chase points activity scraper.
Log in with credentials from .env; scrapes points data and exports to CSV/Excel
with columns: Date, Account Name, Payee, Type, EarnX, Dollars, Points.
"""

import os
import re
import sys
import csv
from pathlib import Path
from datetime import datetime

import yaml
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# Load env first
load_dotenv()

# Default config path
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SESSION_DIR = Path(__file__).resolve().parent / "session"


def _session_paths_for_account(account_name: str, config: dict = None) -> tuple:
    """Return (profile_dir, session_file). Profile is in LOCALAPPDATA so 2FA cookies persist.
    Accounts in the same profile_group share one profile (2FA once per group)."""
    group = (config or {}).get("profile_group", {}).get(account_name) or account_name
    safe = re.sub(r'[<>:"/\\|?*]', "_", group).strip() or "account"
    local_base = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
    profile_dir = local_base / "ChaseScraper" / "profiles" / safe
    session_file = local_base / "ChaseScraper" / "sessions" / f"chase_state_{safe}.json"
    return profile_dir, session_file


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _prompt_browser(msg: str, then: str = "Then press ENTER in this terminal to continue.") -> None:
    """Print a clear prompt so the user knows when to act in the browser."""
    sep = "=" * 60
    print()
    print(sep)
    print("  >>> DO IN BROWSER:", msg)
    print("  >>>", then)
    print(sep)
    print()
    sys.stdout.flush()


def prompt_account_menu(config):
    """Show a numbered menu of account choices. Returns a list of account names (one or all)."""
    choices = config.get("account_choices") or [
        "Ink Pref", "Chase SR", "Freedom-kev", "Ink Cash", "Ink Unlt", "Freedom-dsv", "Sapphire Pref",
    ]
    print()
    print("Select account (credentials and session are per-account):")
    print("-" * 40)
    for i, name in enumerate(choices, 1):
        print(f"  {i}. {name}")
    print(f"  {len(choices) + 1}. All (1-{len(choices)} in succession, sign out after each)")
    print("-" * 40)
    sys.stdout.flush()
    while True:
        try:
            raw = input("Enter number (1-{}): ".format(len(choices) + 1)).strip()
            n = int(raw)
            if 1 <= n <= len(choices):
                return [choices[n - 1]]
            if n == len(choices) + 1:
                return choices
        except (ValueError, EOFError):
            pass
        print("Invalid. Enter a number from 1 to {}.".format(len(choices) + 1))
        sys.stdout.flush()


def get_credentials(account_name: str, config: dict):
    """Get Chase username and password for the selected account from env (see config account_credentials)."""
    creds = (config.get("account_credentials") or {}).get(account_name)
    if creds:
        username = os.environ.get(creds.get("username_env") or "")
        password = os.environ.get(creds.get("password_env") or "")
    else:
        username = os.environ.get("CHASE_USERNAME")
        password = os.environ.get("CHASE_PASSWORD")
    if not username or not password:
        raise SystemExit(
            f"Set credentials for account '{account_name}' in .env. "
            "See config.yaml account_credentials for the env var names (e.g. CHASE_USER_INK_PREF, CHASE_PASSWORD_INK_PREF)."
        )
    return username, password


def normalize_header(text):
    """Map common header labels to our canonical names."""
    t = (text or "").strip().lower()
    if "date" in t:
        return "Date"
    if "payee" in t or "merchant" in t or "description" in t:
        return "Payee"
    if "type" in t or "category" in t:
        return "Type"
    if "earn" in t or "multiplier" in t or "earnx" in t:
        return "EarnX"
    if "dollar" in t or "amount" in t:
        return "Dollars"
    if "point" in t:
        return "Points"
    return None


def _parse_rows_with_header_map(header_cell_texts, data_rows, get_cell_texts):
    """Build header index -> canonical name, then extract row dicts. get_cell_texts(row) returns list of str."""
    header_map = []
    for i, h in enumerate(header_cell_texts):
        canonical = normalize_header(h)
        if canonical:
            header_map.append((i, canonical))
    if not header_map:
        return []
    out = []
    for row_el in data_rows:
        cell_texts = get_cell_texts(row_el)
        if not cell_texts:
            continue
        row_data = {canonical: (cell_texts[idx] if idx < len(cell_texts) else "") for idx, canonical in header_map}
        if any(row_data.values()):
            out.append(row_data)
    return out


def scrape_table_and_account(page, config):
    """Find activity table and optional account name on the current page."""
    selectors = config.get("selectors", {})
    account_name = "Chase"  # default

    # Try to get account/card name from page
    for sel in selectors.get("account_name", "").split(", "):
        sel = sel.strip()
        if not sel:
            continue
        try:
            el = page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text and len(text) < 200:
                    account_name = text
                    break
        except Exception:
            continue

    all_rows = []

    # Strategy 0: Chase Ultimate Rewards page (mds-list-item / transaction-details-item, not a table)
    try:
        items = page.query_selector_all("transaction-details-item mds-list-item, mds-list#posted-activity-list mds-list-item, [id='posted-activity-list'] mds-list-item")
        if not items:
            items = page.query_selector_all("mds-list-item[label][description]")
        for item in items:
            try:
                label = item.get_attribute("label") or ""
                desc = item.get_attribute("description") or ""
                sec_desc = item.get_attribute("secondary-description") or ""
                sec_label = item.get_attribute("secondary-label") or ""
            except Exception:
                continue
            if not label and not sec_label:
                continue
            # description is e.g. "Mar 1, 2026&lt;br/&gt;1.5% earn" -> date and earn type
            parts = desc.replace("&lt;", "<").replace("&gt;", ">").split("<br/>") if desc else ["", ""]
            date_str = (parts[0] or "").strip()
            earn_str = (parts[1] if len(parts) > 1 else "").strip()  # e.g. "1.5% earn" or "3% earn"
            # Normalize to EarnX: "1.5% earn" -> "1.5x", "3% earn" -> "3x"
            earn_x = ""
            if "%" in earn_str:
                m = re.search(r"([\d.]+)\s*%", earn_str)
                if m:
                    earn_x = m.group(1) + "x"
            if not earn_x and earn_str:
                earn_x = "1x"
            dollars = (sec_desc or "").replace("$", "").replace(",", "").strip()
            points = (sec_label or "").replace(" pts", "").replace("pts", "").replace(",", "").strip()
            row = {
                "Date": date_str,
                "Payee": label,
                "Type": "Earn" if "earn" in earn_str.lower() else "",
                "EarnX": earn_x,
                "Dollars": dollars,
                "Points": points,
            }
            if row["Payee"] or row["Points"]:
                all_rows.append(row)
        if all_rows:
            return all_rows, account_name
    except Exception:
        pass

    # Strategy 1: HTML table with tr / th, td
    table_selectors = (selectors.get("activity_table") or "table").split(", ")
    for table_sel in table_selectors:
        table_sel = table_sel.strip()
        if not table_sel:
            continue
        try:
            tables = page.query_selector_all(table_sel)
        except Exception:
            tables = []
        for table in tables:
            try:
                rows = table.query_selector_all("tr")
            except Exception:
                rows = []
            if len(rows) < 2:
                continue
            header_cells = rows[0].query_selector_all("th, td")
            headers = [c.inner_text().strip() for c in header_cells]
            all_rows = _parse_rows_with_header_map(headers, rows[1:], lambda r: [c.inner_text().strip() for c in r.query_selector_all("td, th")])
            if all_rows:
                return all_rows, account_name

    # Strategy 2: ARIA grid ([role=grid] with [role=row] and [role=cell] / [role=gridcell])
    try:
        grids = page.query_selector_all("[role='grid']")
        for grid in grids:
            rows = grid.query_selector_all("[role='row']")
            if len(rows) < 2:
                continue
            header_cells = rows[0].query_selector_all("[role='columnheader'], [role='rowheader'], [role='cell'], [role='gridcell']")
            if not header_cells:
                header_cells = rows[0].query_selector_all("[role='cell'], [role='gridcell']")
            headers = [c.inner_text().strip() for c in header_cells]
            if not any(normalize_header(h) for h in headers):
                continue

            def get_cells(row_el):
                cells = row_el.query_selector_all("[role='cell'], [role='gridcell']")
                return [c.inner_text().strip() for c in cells]

            all_rows = _parse_rows_with_header_map(headers, rows[1:], get_cells)
            if all_rows:
                return all_rows, account_name
    except Exception:
        pass

    # Strategy 3: div/section with row-like children and header-like first row
    try:
        for tag in ["table", "div", "section"]:
            containers = page.query_selector_all(tag)
            for cont in containers:
                row_like = cont.query_selector_all("tr, [role='row'], [class*='row']")
                if len(row_like) < 2:
                    continue
                first = row_like[0]
                cells = first.query_selector_all("th, td, [role='cell'], [role='gridcell'], [class*='cell'], [class*='col']")
                if not cells:
                    continue
                headers = [c.inner_text().strip() for c in cells]
                if not any(normalize_header(h) for h in headers):
                    continue

                def get_cells_row(r):
                    cels = r.query_selector_all("td, th, [role='cell'], [role='gridcell'], [class*='cell'], [class*='col']")
                    return [x.inner_text().strip() for x in cels]

                all_rows = _parse_rows_with_header_map(headers, row_like[1:], get_cells_row)
                if all_rows:
                    return all_rows, account_name
    except Exception:
        pass

    return all_rows, account_name


def add_account_column(rows, account_name):
    """Ensure every row has 'Account Name'."""
    for r in rows:
        if "Account Name" not in r:
            r["Account Name"] = account_name
    return rows


def ensure_column_order(rows, column_order):
    """Return list of dicts with keys in column_order; missing keys get ''."""
    result = []
    for r in rows:
        result.append({k: r.get(k, "") for k in column_order})
    return result


def _account_file_path(account_name: str) -> Path:
    """Path to the ongoing xlsx file for this account (one file per account)."""
    safe = re.sub(r'[<>:"/\\|?*]', "_", account_name).strip() or "account"
    return OUTPUT_DIR / f"{safe}.xlsx"


def _date_sort_key(row: dict) -> tuple:
    """Sort key for date order (chronological = oldest first). Parsed date or (9999,99,99) for unparseable."""
    s = str(row.get("Date", "")).strip()
    if not s:
        return (9999, 99, 99)
    try:
        dt = datetime.strptime(s, "%b %d, %Y")  # e.g. Mar 1, 2026
        return (dt.year, dt.month, dt.day)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%m/%d/%Y")
            return (dt.year, dt.month, dt.day)
        except ValueError:
            return (9999, 99, 99)


def _row_key(row: dict) -> tuple:
    """Key for deduplication: same Date, Payee, Dollars, Points = same transaction."""
    return (
        str(row.get("Date", "")),
        str(row.get("Payee", "")),
        str(row.get("Dollars", "")),
        str(row.get("Points", "")),
    )


def load_existing_rows(path: Path, column_order: list) -> list:
    """Load existing rows from an account xlsx (or csv fallback); return list of dicts with column_order keys."""
    load_path = path
    if not load_path.exists() and path.suffix.lower() == ".xlsx":
        csv_path = path.with_suffix(".csv")
        if csv_path.exists():
            load_path = csv_path
    if not load_path.exists():
        return []
    if load_path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
            wb = openpyxl.load_workbook(load_path, read_only=True, data_only=True)
            ws = wb.active
            rows_iter = ws.iter_rows(min_row=1, values_only=True)
            header = next(rows_iter, None)
            if not header:
                wb.close()
                return []
            keys = [str(h) if h is not None else "" for h in header]
            out = []
            for row in rows_iter:
                r = dict(zip(keys, (v if v is not None else "" for v in row)))
                out.append({k: r.get(k, "") for k in column_order})
            wb.close()
            return out
        except Exception:
            return []
    # CSV fallback (e.g. old file)
    out = []
    with open(load_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            out.append({k: r.get(k, "") for k in column_order})
    return out


def merge_and_save(rows: list, account_name: str, column_order: list) -> tuple:
    """
    Merge new rows into the account's ongoing file; only append transactions not already present.
    Sorted by date (chronological). Saves as xlsx.
    Returns (path, num_new, num_skipped).
    """
    path = _account_file_path(account_name)
    existing = load_existing_rows(path, column_order)
    existing_keys = {_row_key(r) for r in existing}
    new_rows = []
    for r in rows:
        if _row_key(r) not in existing_keys:
            new_rows.append(r)
            existing_keys.add(_row_key(r))
    combined = existing + new_rows
    combined.sort(key=_date_sort_key)
    if combined:
        export_xlsx(combined, path)
    return path, len(new_rows), len(rows) - len(new_rows)


def export_csv(rows, path):
    if not rows:
        return
    keys = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def export_xlsx(rows, path):
    if not rows:
        return
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        export_csv(rows, path.with_suffix(".csv"))
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Points"
    keys = list(rows[0].keys())
    # Header row (green style to match your screenshot)
    header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col, key in enumerate(keys, 1):
        cell = ws.cell(row=1, column=col, value=key)
        cell.fill = header_fill
        cell.font = header_font
    for row_idx, row in enumerate(rows, 2):
        for col_idx, key in enumerate(keys, 1):
            ws.cell(row=row_idx, column=col_idx, value=row.get(key, ""))
    wb.save(path)


def run_scraper(output_format=None, accounts=None):
    config = load_config()
    output_format = output_format or config.get("output", {}).get("default_format", "csv")
    column_order = config.get("output", {}).get("columns") or [
        "Date", "Account Name", "Payee", "Type", "EarnX", "Dollars", "Points"
    ]

    if accounts is None:
        accounts = prompt_account_menu(config)
    last_rows = None

    for account_name in accounts:
        username, password = get_credentials(account_name, config)
        profile_dir, SESSION_FILE = _session_paths_for_account(account_name, config)

        headed = os.environ.get("CHASE_HEADED", "1") == "1"
        chrome = config.get("chase", {})
        login_url = chrome.get("login_url", "https://secure.chase.com/")
        login_timeout = (chrome.get("login_timeout") or 120) * 1000

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        profile_dir.mkdir(parents=True, exist_ok=True)
        if len(accounts) > 1:
            print("\n" + "=" * 50)
            print("Account {} of {}: {}".format(accounts.index(account_name) + 1, len(accounts), account_name))
        else:
            print("Account:", account_name)
        print("Profile (2FA saved here):", profile_dir.resolve())
        sys.stdout.flush()

        with sync_playwright() as p:
            # Persistent profile = real browser profile on disk. Chase "remember this device" cookie lives here so we only do 2FA once per account.
            context_options = {
                "viewport": {"width": 1280, "height": 900},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "accept_downloads": True,
                "ignore_https_errors": False,
            }
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel="chrome" if headed else None,
                    headless=not headed,
                    **context_options,
                )
            except Exception:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    headless=not headed,
                    **context_options,
                )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(login_timeout)

            print("Loading Chase login page...")
            sys.stdout.flush()
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
                if "system-requirements" in page.url:
                    print("Redirecting from system-requirements page...")
                    page.goto(login_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                pass
            print("Waiting for login form...")
            sys.stdout.flush()
            page.wait_for_timeout(3000)

            # Check if we need to log in (login form can be in main page or in an iframe)
            need_login = False
            try:
                content = (page.content() or "").lower()
                if "confirm your identity" in content:
                    need_login = True
                if not need_login:
                    # Main document
                    if page.query_selector("input[name='userId'], input[id*='userId'], input[type='password']"):
                        need_login = True
                if not need_login:
                    # Login form is often inside an iframe — check every frame
                    for frame in page.frames:
                        try:
                            if frame.locator("input[type='password']").first.is_visible(timeout=500):
                                need_login = True
                                break
                            if frame.locator("input[name='userId'], input[id*='userId'], input[type='text']").first.is_visible(timeout=300):
                                need_login = True
                                break
                        except Exception:
                            continue
                # If we're on Chase and URL doesn't look like post-login, assume login needed
                if not need_login and "chase.com" in page.url and "dashboard" not in page.url and "overview" not in page.url and "account" not in page.url:
                    if "sign in" in content or "username" in content or "password" in content:
                        need_login = True
            except Exception:
                need_login = True

            if need_login:
                # Save login page for debugging (so we can see exact DOM/iframes)
                try:
                    debug_path = OUTPUT_DIR / "login_page_debug.html"
                    debug_path.write_text(page.content(), encoding="utf-8")
                    print("Saved login page HTML to", debug_path)
                    sys.stdout.flush()
                except Exception:
                    pass
    
                # Use Playwright frame API: find the frame with the login form, then fill username then password (no JS — works with any iframe)
                print("Looking for login form (username + password)...")
                sys.stdout.flush()
                filled = False
                for frame in page.frames:
                    try:
                        pwd = frame.locator("input[type='password']").first
                        if not pwd.is_visible(timeout=1500):
                            continue
                        # In this frame: first non-password input = username (then password)
                        user_input = frame.locator("input:not([type='password']):not([type='hidden'])").first
                        user_input.wait_for(state="visible", timeout=5000)
                        user_input.click()
                        page.wait_for_timeout(100)
                        user_input.fill(username)
                        print("Filled username.")
                        sys.stdout.flush()
                        page.wait_for_timeout(200)
                        pwd.click()
                        page.wait_for_timeout(100)
                        pwd.fill(password)
                        print("Filled password.")
                        sys.stdout.flush()
                        page.wait_for_timeout(300)
                        btn = frame.locator("button:has-text('Sign in'), input[type='submit'], button[type='submit']").first
                        btn.click()
                        print("Clicked Sign in.")
                        sys.stdout.flush()
                        filled = True
                        break
                    except Exception:
                        continue
                if not filled:
                    print("Could not find login form in any frame; enter credentials manually.")
                    sys.stdout.flush()
                page.wait_for_timeout(5000)
    
                # Only skip 2FA wait when we see the real main page (dashboard/account selector), not just the URL
                main_page_loaded = False
                for _ in range(25):
                    page.wait_for_timeout(1000)
                    content = (page.content() or "").lower()
                    url = (page.url or "").lower()
                    has_2fa_prompt = (
                        "confirm your identity" in content
                        or "verify your identity" in content
                        or "enter the code" in content
                        or "one-time code" in content
                    )
                    if has_2fa_prompt:
                        main_page_loaded = False
                        break
                    # Real dashboard/overview has these; 2FA page does not (no time-sensitive greeting)
                    on_dashboard = (
                        "bank accounts" in content
                        or "credit cards" in content
                        or ("sign out" in content and ("overview" in content or "accounts" in content))
                    )
                    on_account_selector = "account-selector" in url and "choose" in content
                    if on_dashboard or on_account_selector:
                        main_page_loaded = True
                        print("Main page loaded — no 2FA required.")
                        sys.stdout.flush()
                        break
                if not main_page_loaded:
                    _prompt_browser(
                        "Complete 'Confirm Your Identity' — choose Get a text or Get a call and enter the code.",
                        "When you see the Chase dashboard (or account selector), press ENTER in this terminal to continue.",
                    )
                    sys.stdout.flush()
                    input(">>> Press ENTER after completing 2FA... ")
                    print("Continuing...")
                    sys.stdout.flush()
    
                try:
                    page.wait_for_url(re.compile(r"chase\.com", re.I), timeout=login_timeout)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    # Wait until we're past the identity page (e.g. dashboard) so session is fully established
                    for _ in range(30):
                        page.wait_for_timeout(1000)
                        content = (page.content() or "").lower()
                        if "confirm your identity" not in content and ("dashboard" in page.url or "overview" in page.url or "account" in page.url):
                            break
                except PlaywrightTimeout:
                    print("Continuing after timeout; ensure you're on the rewards/activity page.")
    
                try:
                    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                    context.storage_state(path=str(SESSION_FILE))
                    print("Session saved (2FA). Next run may skip login:", SESSION_FILE)
                except Exception as e:
                    print("Could not save session:", e)
                    sys.stdout.flush()
            else:
                print("Using saved session — already logged in.")
                sys.stdout.flush()
    
            # Wait for dashboard if needed, then go to account-selector and select this account by last 4 digits
            dashboard_url = chrome.get("dashboard_url") or "https://secure.chase.com/web/auth/dashboard#/dashboard/overview"
            selector_url = chrome.get("account_selector_url") or "https://ultimaterewardspoints.chase.com/account-selector"
            last4 = (config.get("account_last4") or {}).get(account_name, "").strip()
    
            try:
                if "dashboard" not in page.url and "overview" not in page.url:
                    print("Waiting for dashboard...")
                    sys.stdout.flush()
                    page.goto(dashboard_url, wait_until="load", timeout=30000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                print("Going to account selector...")
                sys.stdout.flush()
                page.goto(selector_url, wait_until="load", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(1000)
                try:
                    page.wait_for_url(re.compile(r"account-selector|ultimaterewardspoints"), timeout=3000)
                except Exception:
                    pass
    
                # If Chase is asking for 2FA (e.g. session was stale), pause for user to complete it
                if "confirm your identity" in (page.content() or "").lower():
                    _prompt_browser(
                        "Chase is asking to confirm your identity. Complete 2FA in the browser.",
                        "When you see the account selector or dashboard, press ENTER here to continue.",
                    )
                    sys.stdout.flush()
                    input(">>> Press ENTER after completing 2FA... ")
                    print("Continuing...")
                    sys.stdout.flush()
                    page.wait_for_timeout(1000)
    
                if last4:
                    # Exact structure from Chase: body.account-selector-container > section.card-section > mds-list > mds-list-item[label="...1827"][href="..."]
                    selected = False
                    try:
                        page.wait_for_selector("body.account-selector-container section.card-section mds-list-item", timeout=8000)
                        page.wait_for_timeout(500)
                    except Exception:
                        pass
                    # Primary: mds-list-item has label and href in light DOM — get href and navigate (no click needed)
                    try:
                        card = page.locator(f'mds-list-item[label*="{last4}"]').first
                        card.wait_for(state="visible", timeout=6000)
                        href = card.get_attribute("href")
                        if href:
                            page.goto(href, wait_until="load", timeout=20000)
                            try:
                                page.wait_for_load_state("networkidle", timeout=3000)
                            except Exception:
                                pass
                            print("Selected account ending in", last4)
                            sys.stdout.flush()
                            selected = True
                    except Exception as e1:
                        pass
                    if not selected:
                        try:
                            href_or_clicked = page.evaluate("""(last4) => {
                                const items = document.querySelectorAll('section.card-section mds-list-item');
                                for (const el of items) {
                                    const label = el.getAttribute('label') || '';
                                    if (label.indexOf(last4) !== -1) {
                                        const href = el.getAttribute('href') || '';
                                        if (href) return { href: href };
                                        if (el.shadowRoot) {
                                            const a = el.shadowRoot.querySelector('a[href*="ultimaterewardspoints"]');
                                            if (a) { a.click(); return { clicked: true }; }
                                        }
                                        el.click();
                                        return { clicked: true };
                                    }
                                }
                                return null;
                            }""", last4)
                            if href_or_clicked and href_or_clicked.get("href"):
                                page.goto(href_or_clicked["href"], wait_until="load", timeout=20000)
                                try:
                                    page.wait_for_load_state("networkidle", timeout=3000)
                                except Exception:
                                    pass
                                print("Selected account ending in", last4, "(JS)")
                                sys.stdout.flush()
                                selected = True
                            elif href_or_clicked and href_or_clicked.get("clicked"):
                                page.wait_for_timeout(2000)
                                selected = True
                        except Exception as e0:
                            print("JS selection:", e0)
                            sys.stdout.flush()
                    if not selected:
                        try:
                            link = page.get_by_role("link", name=re.compile(re.escape(last4)))
                            link.first.wait_for(state="visible", timeout=6000)
                            link.first.click()
                            print("Selected account ending in", last4, "(link)")
                            sys.stdout.flush()
                            page.wait_for_timeout(2000)
                            selected = True
                        except Exception as e2:
                            print("Could not select account for digits", last4, "—", e2)
                            sys.stdout.flush()
                            print(">>> Please click the account card in the browser, then press ENTER here to continue.")
                            sys.stdout.flush()
                            input()
                else:
                    print("No account_last4 for", account_name, "in config — select account manually.")
                    sys.stdout.flush()
            except Exception as e:
                print("Navigation to account selector failed:", e)
                sys.stdout.flush()
    
            # Auto-navigate: click "See rewards activity" then "See all transactions" (keep Enter prompt as fallback)
            rewards_url = chrome.get("rewards_activity_url")
            if rewards_url:
                print("Navigating to rewards activity URL...")
                sys.stdout.flush()
                page.goto(rewards_url, wait_until="load", timeout=30000)
            else:
                try:
                    print("Clicking 'See rewards activity'...")
                    sys.stdout.flush()
                    btn = (
                        page.get_by_role("button", name=re.compile(r"See rewards activity", re.I))
                        .or_(page.get_by_role("link", name=re.compile(r"See rewards activity", re.I)))
                        .or_(page.get_by_text("See rewards activity", exact=False))
                        .first
                    )
                    btn.wait_for(state="visible", timeout=10000)
                    btn.click()
                    page.wait_for_load_state("load", timeout=15000)
                    page.wait_for_timeout(2000)
                except Exception as e1:
                    print("Could not click See rewards activity:", e1)
                    sys.stdout.flush()
                try:
                    print("Clicking 'See all transactions'...")
                    sys.stdout.flush()
                    btn2 = (
                        page.get_by_role("button", name=re.compile(r"See all transactions", re.I))
                        .or_(page.get_by_role("link", name=re.compile(r"See all transactions", re.I)))
                        .or_(page.get_by_text("See all transactions", exact=False))
                        .first
                    )
                    btn2.wait_for(state="visible", timeout=10000)
                    btn2.click()
                    page.wait_for_load_state("load", timeout=15000)
                    page.wait_for_timeout(2000)
                except Exception as e2:
                    print("Could not click See all transactions:", e2)
                    sys.stdout.flush()
    
            # Click "See more transactions" until it becomes "Back to top" (all transactions loaded)
            max_load_more = 200
            for n in range(max_load_more):
                see_more = (
                    page.get_by_role("button", name=re.compile(r"See more transactions", re.I))
                    .or_(page.get_by_role("link", name=re.compile(r"See more transactions", re.I)))
                    .or_(page.get_by_text("See more transactions", exact=False))
                    .first
                )
                try:
                    if see_more.is_visible(timeout=2000):
                        see_more.click()
                        page.wait_for_timeout(1500)
                        if (n + 1) % 10 == 0 or n < 3:
                            print("Loaded more transactions...", n + 1)
                            sys.stdout.flush()
                        continue
                except Exception:
                    pass
                back_to_top = page.get_by_role("button", name=re.compile(r"Back to top", re.I)).or_(page.get_by_text("Back to top", exact=False)).first
                try:
                    if back_to_top.is_visible(timeout=1000):
                        print("All transactions loaded (Back to top visible).")
                        sys.stdout.flush()
                        break
                except Exception:
                    pass
                break
            else:
                print("Reached max 'See more' clicks; continuing with current list.")
                sys.stdout.flush()
    
            print("Scraping current page for points activity table...")
            sys.stdout.flush()
            page.wait_for_timeout(5000)  # allow dynamic content (e.g. React) to render
            rows, _ = scrape_table_and_account(page, config)
            if rows:
                rows = add_account_column(rows, account_name)
            rows = ensure_column_order(rows, column_order)
    
            if not rows:
                debug_path = OUTPUT_DIR / "last_page_debug.html"
                try:
                    debug_path.write_text(page.content(), encoding="utf-8")
                    print(f"No activity table found. Page HTML saved to {debug_path} for inspection.")
                except Exception:
                    print("No activity table found. Navigate to your Chase rewards/points activity page and run again, or check config.yaml selectors.")
                print("Tip: Next run, open the rewards/points activity page in the browser within 90 seconds so the script can detect it.")
            else:
                print(f"Scraped {len(rows)} rows. Account: {account_name}")
    
            # Backup cookies to JSON (profile is the source of truth for 2FA)
            try:
                SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(SESSION_FILE))
            except Exception:
                pass
    
            # Sign out of Chase before closing (clear session for next run)
            try:
                print("Signing out...")
                sys.stdout.flush()
                try:
                    page.goto("https://secure.chase.com/web/auth/logout", wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                try:
                    sign_out = (
                        page.get_by_role("link", name=re.compile(r"Sign out|Log out|Log off", re.I))
                        .or_(page.get_by_role("button", name=re.compile(r"Sign out|Log out|Log off", re.I)))
                        .or_(page.get_by_text(re.compile(r"Sign out|Log out|Log off", re.I)))
                        .first
                    )
                    if sign_out.is_visible(timeout=2000):
                        sign_out.click()
                        page.wait_for_timeout(2000)
                except Exception:
                    pass
                print("Signed out.")
                sys.stdout.flush()
            except Exception as e:
                print("Sign out skipped:", e)
                sys.stdout.flush()
    
            context.close()

        # Merge into ongoing file for this account (one file per account); only insert new transactions
        if rows:
            last_rows = rows
            out_path, num_new, num_skipped = merge_and_save(rows, account_name, column_order)
            print(f"Saved to {out_path}: {num_new} new transaction(s) added, {num_skipped} already present.")
            sys.stdout.flush()

    return last_rows


if __name__ == "__main__":
    run_scraper()
