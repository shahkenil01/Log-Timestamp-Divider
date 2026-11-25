@echo off
title Push Updates To GitHub (Auto Deploy to Friends)
color 0A
echo ========================================================
echo   Auto-Deploy Tool: Push Updates to Live Server
echo ========================================================
echo.

cd /d "%~dp0"

git status
echo.
set /p commit_msg="Enter update message (press Enter for auto-timestamp): "
if "%commit_msg%"=="" set commit_msg=Update code: %date% %time%

git add .
git commit -m "%commit_msg%"
echo.
echo Pushing to GitHub...
git push origin main

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo   SUCCESS! Updates pushed to GitHub.
    echo   Your live cloud server (Render / Hugging Face) is
    echo   now automatically rebuilding with latest changes!
    echo ========================================================
) else (
    echo.
    echo [!] Push failed or remote origin not connected yet.
    echo Please ensure you added your GitHub repository URL:
    echo git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
)

echo.
pause
