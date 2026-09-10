# -*- coding: utf-8 -*-
"""
Suno Downloader - 配布用パッケージビルドスクリプト
PyInstallerでexe化し、ffmpeg/ffprobeを同梱した上でZIPパッケージを作成します。
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR / "dist"
APP_DIST_DIR = DIST_DIR / "SunoDownloader"
ZIP_PATH = DIST_DIR / "SunoDownloader_Windows.zip"

def find_binary(name: str) -> Path | None:
    """システムのPATHまたはWinGetからバイナリ（ffmpeg.exe等）を探します。"""
    which_path = shutil.which(name)
    if which_path:
        p = Path(which_path).resolve()
        # ショートカットやリンクの場合の実体解決
        return p

    # WinGetの典型的なインストール先を検索
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        winget_links = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
        if winget_links.exists():
            return winget_links.resolve()

        winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_packages.exists():
            found = list(winget_packages.glob(f"**/{name}.exe"))
            if found:
                return found[0].resolve()

    return None

def main():
    print("=" * 60)
    print("     Suno Downloader 配布パッケージ ビルドツール")
    print("=" * 60)
    print()

    # 1. PyInstallerの確認
    print("[1/4] PyInstaller を確認中...")
    try:
        import PyInstaller
        print(f"  PyInstaller バージョン: {PyInstaller.__version__}")
    except ImportError:
        print("  [ERROR] PyInstaller がインストールされていません。pip install pyinstaller を実行してください。")
        sys.exit(1)

    # 2. ビルド実行
    print()
    print("[2/4] アプリケーションをビルド中（数十秒かかります）...")
    spec_path = BASE_DIR / "SunoDownloader.spec"
    cmd = [sys.executable, "-m", "PyInstaller", str(spec_path), "--noconfirm"]
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        print("  [ERROR] PyInstallerのビルドに失敗しました。")
        sys.exit(1)

    # 3. FFmpeg / ffprobe を同梱コピー
    print()
    print("[3/4] FFmpeg と ffprobe を配布フォルダに同梱中...")
    APP_DIST_DIR.mkdir(parents=True, exist_ok=True)

    for bin_name in ["ffmpeg", "ffprobe"]:
        bin_path = find_binary(bin_name)
        if bin_path and bin_path.exists():
            dest = APP_DIST_DIR / f"{bin_name}.exe"
            shutil.copy2(bin_path, dest)
            print(f"  [OK] {bin_name}.exe を同梱しました: {bin_path}")
        else:
            print(f"  [WARNING] {bin_name}.exe が見つかりませんでした。手動で {APP_DIST_DIR} に配置してください。")

    # 4. 配布用ZIPの作成
    print()
    print("[4/4] 配布用ZIPアーカイブを作成中...")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    shutil.make_archive(
        base_name=str(DIST_DIR / "SunoDownloader_Windows"),
        format="zip",
        root_dir=str(DIST_DIR),
        base_dir="SunoDownloader"
    )
    print(f"  [OK] 配布用ZIPを作成しました: {ZIP_PATH}")

    print()
    print("=" * 60)
    print("  【大成功】配布用パッケージが完成しました！")
    print()
    print(f"  ・配布フォルダ: {APP_DIST_DIR}")
    print(f"  ・配布用ZIP:    {ZIP_PATH}")
    print()
    print("  このZIPファイルを他のWindows PCに配布して解凍すれば、")
    print("  PythonもFFmpegもインストール不要で、")
    print("  SunoDownloader.exe をダブルクリックするだけで即座に動きます！")
    print("=" * 60)

if __name__ == "__main__":
    main()
