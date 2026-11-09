@echo off
REM Radar local fallback refresh - wrapper for Windows Task Scheduler
REM bash is required (Git Bash). Adjust BASH path if needed.
set "BASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=C:\Program Files\Git\usr\bin\bash.exe"
"%BASH%" -lc "bash ~/ai-news-radar-gh/local_refresh.sh"
