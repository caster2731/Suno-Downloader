@echo off
title Suno Downloader

REM 作業ディレクトリをバッチファイルの場所に移動
cd /d "%~dp0"

echo ========================================================
echo         Suno Downloader を起動しています...
echo ========================================================
echo.

REM 依存ライブラリの確認とインストール
echo [1/2] 必要なライブラリを確認中...
python -m pip install -r requirements.txt --quiet

REM 既定のブラウザでアプリを開く
echo [2/2] アプリケーションを起動中...
start "" "http://127.0.0.1:8000"

REM FastAPI サーバー起動
python app.py

pause
