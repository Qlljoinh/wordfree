@echo off
rem ============================================================
rem  WordFree — сборка WordFree.exe НА WINDOWS
rem  Требования: Python 3.11+ (python.org), интернет.
rem  Положите этот файл в корень проекта и запустите двойным щелчком.
rem ============================================================
cd /d "%~dp0"

echo [1/3] Установка зависимостей...
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements-win.txt

echo [2/3] Сборка exe (PyInstaller)...
py -3 -m PyInstaller --onefile --windowed --name WordFree ^
  --icon assets\wordfree.ico ^
  --add-data "fonts\*.ttf;fonts" ^
  --add-data "dictionaries\hunspell\*;dictionaries\hunspell" ^
  --add-data "dictionaries\*.gz;dictionaries" ^
  --hidden-import spylls --hidden-import spylls.hunspell ^
  --hidden-import spellchecker --hidden-import docx ^
  --hidden-import language_tool_python --hidden-import reportlab ^
  --hidden-import PIL.ImageTk --hidden-import requests ^
  --collect-subdata language_tool_python ^
  main.py

echo [3/3] Готово: dist\WordFree.exe
pause
