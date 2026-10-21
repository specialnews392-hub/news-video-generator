@echo off
cd /d "%~dp0"
echo Checking for changes...
git add main.py static/ services/ *.py *.bat *.txt *.html *.css
git diff-index --quiet HEAD || git commit -m "Update code and generator fixes"
echo Pushing to GitHub as n09795213-afk...
git remote set-url origin https://n09795213-afk@github.com/n09795213-afk/news-video-generator.git
git push origin main
echo Done!
pause
