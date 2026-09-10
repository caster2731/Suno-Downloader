# -*- coding: utf-8 -*-
"""
Suno Downloader - Webアプリケーションサーバー
FastAPIによる軽量APIサーバーおよび静的UIホスティングを提供します。
"""

import os
import sys
import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Windows環境におけるPython 3.13のasyncioアサーションエラー（AssertionError: Data should not be empty）を防止
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

import suno_service


# 基本ディレクトリの設定（開発環境およびPyInstaller exe環境の両方に対応）
def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        if hasattr(sys, '_MEIPASS'):
            meipass_static = Path(sys._MEIPASS) / "static"
            if meipass_static.exists():
                return Path(sys._MEIPASS)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
STATIC_DIR = BASE_DIR / "static"

# ダウンロード保存先フォルダ（exeと同じディレクトリに downloads フォルダを作成）
APP_ROOT = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
DEFAULT_DOWNLOADS_DIR = APP_ROOT / "downloads"
DEFAULT_DOWNLOADS_DIR.mkdir(exist_ok=True)


app = FastAPI(title="Suno Downloader", version="1.0.0")

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- リクエスト/レスポンスモデル定義 ---
class ParseRequest(BaseModel):
    text: str


class DownloadItemRequest(BaseModel):
    uuid: str
    title: str
    artist: str
    image_url: str
    format: str = "mp3"
    output_dir: Optional[str] = None
    audio_url: Optional[str] = None
    candidate_urls: Optional[List[str]] = None


class OpenFolderRequest(BaseModel):
    folder_path: Optional[str] = None


# --- APIエンドポイント ---

@app.get("/api/config")
def get_config():
    """アプリのデフォルト設定（保存先フォルダパス等）を返却します。"""
    return {
        "default_download_dir": str(DEFAULT_DOWNLOADS_DIR),
        "available_formats": ["mp3", "m4a"]
    }


@app.post("/api/parse")
def parse_urls(req: ParseRequest):
    """
    入力テキストからSuno楽曲URL/UUIDを抽出し、メタデータ（曲名・アーティスト・画像）を取得します。
    """
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="URLまたはテキストを入力してください。")

    uuids = suno_service.extract_uuids(req.text)
    if not uuids:
        return {"songs": [], "message": "有効なSunoの楽曲URLが見つかりませんでした。"}

    results = []
    for uuid in uuids:
        meta = suno_service.fetch_song_metadata(uuid)
        results.append(meta)

    return {
        "count": len(results),
        "songs": results
    }


@app.post("/api/download-single")
def download_single(req: DownloadItemRequest):
    """
    1曲のダウンロードとフォーマット変換、メタデータ埋め込みを実行します。
    """
    target_dir = req.output_dir if req.output_dir and os.path.isdir(req.output_dir) else str(DEFAULT_DOWNLOADS_DIR)

    try:
        res = suno_service.process_song_download(
            uuid=req.uuid,
            title=req.title,
            artist=req.artist,
            image_url=req.image_url,
            format_type=req.format,
            output_dir=target_dir,
            audio_url=req.audio_url,
            candidate_urls=req.candidate_urls
        )
        return {
            "status": "success",
            "data": res
        }
    except Exception as e:
        print(f"ダウンロード処理エラー ({req.uuid}): {e}")
        return {
            "status": "error",
            "message": str(e),
            "uuid": req.uuid
        }


@app.post("/api/open-folder")
def open_folder(req: OpenFolderRequest):
    """
    保存先フォルダをWindowsのエクスプローラーで開きます。
    """
    target = req.folder_path if req.folder_path and os.path.exists(req.folder_path) else str(DEFAULT_DOWNLOADS_DIR)
    try:
        if sys.platform == "win32":
            os.startfile(target)
        else:
            subprocess.Popen(["xdg-open", target])
        return {"status": "success", "opened_path": target}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"フォルダを開けませんでした: {e}")


@app.get("/api/download-file")
def download_file_browser(filepath: str = Query(...)):
    """
    ローカルに生成された音声ファイルをブラウザ経由でダウンロードさせるエンドポイントです。
    """
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="ファイルが見つかりません。")
    filename = os.path.basename(filepath)
    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream"
    )


# 静的UIファイルのルーティング
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import webbrowser
    import threading
    import time

    def open_browser():
        time.sleep(1.2)
        webbrowser.open("http://127.0.0.1:8000")

    # 別スレッドでブラウザを自動起動
    threading.Thread(target=open_browser, daemon=True).start()

    print("==================================================")
    print("  Suno Downloader サーバーを起動しました")
    print("  ブラウザで http://127.0.0.1:8000 を開いています...")
    print("==================================================")
    # PyInstaller環境ではappインスタンスを直接渡すのが必須
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False, log_level="info")


