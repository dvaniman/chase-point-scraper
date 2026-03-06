# Run this in Cursor's terminal (PowerShell) to push to GitHub.
# Requires: gh CLI installed and authenticated (gh auth login).

$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

# Safe directory for network path (Git reports path with //file02/... on this share)
git config --global --add safe.directory '%(prefix)///file02/public/DOCUMENT/Don/Personal/Travel/Chase Data'

# Stage only safe files (no .env, config.yaml, output, session)
git add .gitignore .env.example config.example.yaml README.md requirements.txt scraper.py scraper_gui.py README-GUI.md push-to-github.ps1
if (Test-Path ".cursor/sandbox.json") { git add .cursor/sandbox.json }
if (Test-Path ".cursor/CURSOR_TERMINAL_FIX.md") { git add .cursor/CURSOR_TERMINAL_FIX.md }

$status = git status --porcelain
if ($status) {
    git commit -m "Initial commit: Chase point scraper and Windows GUI"
}

# Ensure main branch
$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne "main") {
    git branch -M main
}

# Create repo on GitHub if it doesn't exist (skip adding remote - origin already set in .git/config)
# Ignore error when repo already exists (Name already exists on this account)
try { gh repo create chase-point-scraper --public --source=. --description "Chase Ultimate Rewards points scraper with Windows GUI" 2>$null } catch { }

# Push
git push -u origin main

Write-Host "Done. Repo: https://github.com/dvaniman/chase-point-scraper"
