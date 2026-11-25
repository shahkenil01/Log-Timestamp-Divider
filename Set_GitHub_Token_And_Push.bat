@echo off
title GitHub Token Authentication & Push
color 0B
echo ========================================================
echo   GitHub Push Authentication Helper
echo ========================================================
echo.
echo GitHub ab password accept nahi karta, sirf "Personal Access Token" leta he.
echo Token banane ke liye (10 seconds):
echo 1. Browser me ye link open karein:
echo    https://github.com/settings/tokens
echo 2. "Generate new token (classic)" par click karein.
echo 3. "repo" wale checkbox par tick lagayein aur Generate dabayein.
echo 4. Token copy karein (ghp_xxxxxxxxxxxx).
echo.
echo ========================================================
echo.
set /p ghtoken="Paste your GitHub Token here: "

if "%ghtoken%"=="" (
    echo [!] No token entered. Exiting...
    pause
    exit /b
)

cd /d "%~dp0"
echo.
echo Setting remote URL with your token...
git remote set-url origin https://%ghtoken%@github.com/shahkenil01/Log-Timestamp-Divider.git

echo.
echo Pushing to GitHub (main branch)...
git push -u origin main

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo   [SUCCESS] Code successfully pushed to GitHub!
    echo   Ab Render.com par jakar repository select karein
    echo   aur "Deploy Web Service" dabayein!
    echo ========================================================
) else (
    echo.
    echo [!] Push failed. Please check if token is valid and has "repo" permission.
)

echo.
pause
