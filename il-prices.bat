@echo off
chcp 65001 >nul
python -c "import il_supermarket_scarper, lxml" 2>nul || (
  echo Installing requirements...
  python -m pip install -r "%~dp0requirements.txt"
)
python "%~dp0il_prices.py" %*
