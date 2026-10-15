@echo off
cd /d "%~dp0"
echo Pushing to GitHub as n09795213-afk...
git remote set-url origin https://n09795213-afk@github.com/n09795213-afk/news-video-generator.git
git push -u origin main
echo Done!
pause
