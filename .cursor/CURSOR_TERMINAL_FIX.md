# Fixing Agent Terminal & Git in Cursor

So the Agent can run git/terminal commands and you can see output, try these in order.

## 1. Project sandbox (done)

This project has `.cursor/sandbox.json` that:
- Disables the sandbox for this workspace (`"type": "insecure_none"`) so commands run with full access.
- Allows all network (`"default": "allow"`) so `git push` and `gh` can reach GitHub.

Start a **new chat** or **reload the window** (Ctrl+Shift+P → "Developer: Reload Window") so the new sandbox config is picked up.

## 2. If you still see no terminal output

Cursor has a known bug where Agent terminal output is empty even though commands run. Try:

1. **Close Cursor.**
2. **Delete workspace storage** (resets terminal state; chat history for workspaces may be cleared):
   - Open: `%APPDATA%\Cursor\User\workspaceStorage`
   - Delete the folder whose name is a long hash (or all folders to reset every workspace).
3. **Start Cursor again**, open this project, and run an Agent command that uses the terminal.

Reference: [Cursor Forum - Terminal output not showing](https://forum.cursor.com/t/solved-terminal-output-not-showing-in-agent-mode-delete-workspacestorage-folder-v2-1-39-windows-11/144751)

## 3. Windows: Agent uses WSL2

On Windows, the Agent runs terminal commands **inside WSL2**, not in your PowerShell. So:

- The shell is Linux (e.g. bash), not PowerShell.
- Your workspace path `\\file02\...` may be under `/mnt/` or similar in WSL2.
- `gh` and `git` must be installed and authenticated **inside WSL2** for Agent pushes to work.

If you need Agent to run in **your** PowerShell instead, there is no Cursor setting for that today; the workaround is to run the commands yourself in Cursor’s terminal (Ctrl+`).

## 4. Cursor Settings (optional)

- **Cursor Settings → Agents → Auto-Run**  
  - "Ask Every Time" lets you approve each command (and may run it in a less restricted context).  
  - "Run Everything" runs commands automatically; with `insecure_none` they are not sandboxed.
- **Auto-run network access**  
  - "Allow All" ensures git/gh can reach the network even if sandbox is used elsewhere.

---

After 1 (and 2 if needed), start a new Agent chat and ask it to run a simple command (e.g. `git status`). You should see output in the Agent’s terminal panel.
