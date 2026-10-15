@echo off
cd /d "%~dp0"
echo Initializing Git repository for NEWS...
git init
git add .
git commit -m "Initial commit for News Video Generator"
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/n09795213-afk/news-video-generator.git
echo Pushing to GitHub...
git push -u origin main
echo Done!
pause
