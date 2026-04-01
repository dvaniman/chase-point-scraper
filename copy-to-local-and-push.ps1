# Run this from PowerShell to copy the project to local Git folder and create the GitHub repo.
# Run from: \\file02\public\DOCUMENT\Don\Personal\Travel\Chase Data

$source = "\\file02\public\DOCUMENT\Don\Personal\Travel\Chase Data"
$dest   = "C:\Users\don.VMC\AppData\Local\Git\chase-point-scraper"

New-Item -ItemType Directory -Force -Path "C:\Users\don.VMC\AppData\Local\Git" | Out-Null
New-Item -ItemType Directory -Force -Path $dest | Out-Null

Write-Host "Copying project to $dest ..."
Copy-Item -Path "$source\*" -Destination $dest -Recurse -Force
Write-Host "Copy done."

Set-Location $dest
git init
git remote add origin https://github.com/dvaniman/chase-point-scraper.git
git add .gitignore .env.example config.example.yaml README.md requirements.txt scraper.py scraper_gui.py README-GUI.md
git commit -m "Initial commit: Chase point scraper and Windows GUI"
git branch -M main
Write-Host "Creating repo on GitHub (requires gh auth)..."
gh repo create chase-point-scraper --public --source=. --remote=origin --push
Write-Host "Done. Check https://github.com/dvaniman/chase-point-scraper"
