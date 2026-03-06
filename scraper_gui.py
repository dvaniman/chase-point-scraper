"""
Chase point scraper — Windows GUI launcher.
Uses tkinter (built-in). Run with: python scraper_gui.py
Or run the .exe with config.yaml and .env in the same folder as the .exe.
"""
import os
import sys
import threading
import queue
from pathlib import Path

# Project root: when running as .exe (PyInstaller), use the folder containing the .exe.
# Otherwise use the folder containing this script.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    # PyInstaller extracts to a temp folder; Playwright must use the user's browser cache, not the exe folder.
    _playwright_browsers = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~") + os.sep + "AppData" + os.sep + "Local")) / "ms-playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_playwright_browsers)
else:
    ROOT = Path(__file__).resolve().parent
# Run from project folder so config/env and scraper find files
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# Queue-based stdin so GUI can "press Enter" when scraper waits for 2FA
_input_queue = queue.Queue()
_original_stdin = sys.stdin


class QueueStdin:
    """File-like object that reads from a queue; used to replace sys.stdin so input() can be driven by GUI."""
    def readline(self, size=-1):
        try:
            return _input_queue.get(timeout=86400)  # block until GUI sends
        except queue.Empty:
            return "\n"

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


def run_scraper_with_gui(log_widget, continue_btn, accounts):
    """Run scraper in thread; redirect stdout to log_widget; use QueueStdin for input()."""
    def worker():
        try:
            sys.stdin = QueueStdin()
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            # PyInstaller .exe without console can have stdout/stderr as None
            if old_stdout is None:
                old_stdout = open(os.devnull, "w")
            if old_stderr is None:
                old_stderr = open(os.devnull, "w")

            class StdoutRedirect:
                def __init__(self, widget, fallback):
                    self.widget = widget
                    self.fallback = fallback
                def write(self, s):
                    if s.strip():
                        self.widget.after(0, lambda: _append_log(self.widget, s))
                    if self.fallback is not None:
                        self.fallback.write(s)
                def flush(self):
                    if self.fallback is not None:
                        self.fallback.flush()

            def _append_log(w, text):
                w.insert(tk.END, text)
                w.see(tk.END)

            sys.stdout = StdoutRedirect(log_widget, old_stdout)
            sys.stderr = sys.stdout

            from scraper import run_scraper
            run_scraper(accounts=accounts)

        except Exception as e:
            log_widget.after(0, lambda: _append_log(log_widget, f"\nError: {e}\n"))
            import traceback
            log_widget.after(0, lambda: _append_log(log_widget, traceback.format_exc()))
        finally:
            sys.stdin = _original_stdin
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            continue_btn.after(0, lambda: continue_btn.config(state=tk.DISABLED))
            log_widget.after(0, lambda: _append_log(log_widget, "\n--- Done ---\n"))

    t = threading.Thread(target=worker, daemon=True)
    t.start()


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    config_path = ROOT / "config.yaml"

    def show_folder_error(title, detail, missing_path=None):
        is_exe = getattr(sys, "frozen", False)
        if is_exe:
            where = "Put config.yaml (and .env) in the same folder as this program (.exe)."
        else:
            where = "Run from that folder, or set your shortcut's 'Start in' to that folder."
        msg = (
            f"{detail}\n\n"
            f"Expected folder (config & .env go here):\n  {ROOT}\n\n"
            "To fix:\n"
            f"• {where}\n\n"
        )
        if not is_exe:
            msg += (
                "• Or in PowerShell:\n"
                f"  cd \"{ROOT}\"\n  python scraper_gui.py\n"
            )
        if missing_path is not None:
            msg = f"Missing or wrong path:\n  {missing_path}\n\n" + msg
        messagebox.showerror(title, msg)

    if not config_path.is_file():
        show_folder_error(
            "Config not found",
            "config.yaml was not found in the same folder as scraper_gui.py.",
            missing_path=str(config_path),
        )
        return

    try:
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except Exception as e:
        messagebox.showerror(
            "Config error",
            f"Could not load config.yaml:\n{e}\n\nExpected folder: {ROOT}",
        )
        return

    choices = config.get("account_choices") or []
    if not choices:
        messagebox.showwarning("No accounts", "Add account_choices to config.yaml.")
        return

    root = tk.Tk()
    root.title("Chase point scraper")
    root.minsize(500, 400)
    root.geometry("700x500")

    main = ttk.Frame(root, padding=10)
    main.pack(fill=tk.BOTH, expand=True)

    ttk.Label(main, text="Account").pack(anchor=tk.W)
    account_var = tk.StringVar(value=choices[0] if choices else "")
    combo = ttk.Combobox(main, textvariable=account_var, values=choices + ["All"], state="readonly", width=40)
    combo.pack(fill=tk.X, pady=(0, 10))
    if choices:
        combo.set(choices[0])

    btn_frame = ttk.Frame(main)
    btn_frame.pack(fill=tk.X, pady=(0, 5))

    def on_run():
        sel = account_var.get()
        if sel == "All":
            accounts = choices
        else:
            accounts = [sel]
        log.config(state=tk.NORMAL)
        log.delete(1.0, tk.END)
        log.insert(tk.END, f"Running for: {', '.join(accounts)}\n\n")
        continue_btn.config(state=tk.NORMAL)
        run_scraper_with_gui(log, continue_btn, accounts)

    run_btn = ttk.Button(btn_frame, text="Run scraper", command=on_run)
    run_btn.pack(side=tk.LEFT, padx=(0, 5))

    continue_btn = ttk.Button(btn_frame, text="Continue (after 2FA)", state=tk.DISABLED, command=lambda: _input_queue.put("\n"))
    continue_btn.pack(side=tk.LEFT)
    ttk.Label(btn_frame, text="— click when Chase 2FA is done", foreground="gray").pack(side=tk.LEFT, padx=(5, 0))

    ttk.Label(main, text="Log").pack(anchor=tk.W, pady=(10, 0))
    log = scrolledtext.ScrolledText(main, height=20, state=tk.DISABLED, wrap=tk.WORD)
    log.pack(fill=tk.BOTH, expand=True, pady=5)

    root.mainloop()


if __name__ == "__main__":
    main()
