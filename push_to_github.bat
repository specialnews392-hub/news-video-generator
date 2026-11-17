@echo off
cd /d "%~dp0"
echo Checking for changes...
git add main.py static/ services/ *.py *.bat *.sh *.txt *.html *.css requirements.txt
git diff-index --quiet HEAD || git commit -m "Configure for new repository s90706098zarub-ui/video"
echo Pushing to GitHub as specialnews392-hub...
git remote set-url origin https://specialnews392-hub@github.com/specialnews392-hub/news-video-generator.git
git push -u origin main
if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================
    echo  SUCCESS: Code pushed to GitHub!
    echo ========================================
) else (
    echo.
    echo ========================================
    echo  ERROR: Push failed! See error above.
    echo ========================================
)
pause
