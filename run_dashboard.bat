@echo off
REM Double-click to launch the dashboard locally in your browser.
REM Closes when you close this window (or press Ctrl+C).
cd /d "%~dp0"
py -m streamlit run dashboard\Home.py
pause
