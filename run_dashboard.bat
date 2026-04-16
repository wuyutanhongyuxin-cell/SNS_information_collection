@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
uv run --python 3.12 ^
  --with streamlit ^
  --with plotly ^
  --with pandas ^
  --with wordcloud ^
  --with streamlit-extras ^
  --with streamlit-option-menu ^
  streamlit run scripts\app.py
