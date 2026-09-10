@echo off
title Suno Downloader - 配布パッケージビルド
cd /d "%~dp0"
python build_package.py
pause
