@echo off
echo Starting Backlink AI Dashboard...
echo.
echo Open in browser: http://localhost:8000
echo.
python -m uvicorn src.presentation.app:app --host 0.0.0.0 --port 8000
pause
