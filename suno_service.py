# -*- coding: utf-8 -*-
"""
Suno Downloader - サービスロジック
Sunoの楽曲メタデータ取得、音源ダウンロード、フォーマット変換、メタデータ＆アートワーク埋め込みを担当します。
"""

import os
import sys
import re
import html
import tempfile
import subprocess
import requests
from bs4 import BeautifulSoup
from mutagen.mp4 import MP4, MP4Cover
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC
from mutagen.mp3 import MP3

from io import BytesIO
from PIL import Image
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_app_dir() -> str:
    """アプリケーションの基準ディレクトリを取得します（開発環境・PyInstaller対応）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_ffmpeg_path() -> str:
    """ffmpegの実行ファイルパスを取得します（同梱バイナリ最優先、なければシステムPATH）。"""
    app_dir = get_app_dir()
    candidates = [
        os.path.join(app_dir, "ffmpeg.exe"),
        os.path.join(app_dir, "bin", "ffmpeg.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "ffmpeg.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "bin", "ffmpeg.exe")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "ffmpeg"


def get_ffprobe_path() -> str:
    """ffprobeの実行ファイルパスを取得します（同梱バイナリ最優先、なければシステムPATH）。"""
    app_dir = get_app_dir()
    candidates = [
        os.path.join(app_dir, "ffprobe.exe"),
        os.path.join(app_dir, "bin", "ffprobe.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "ffprobe.exe"),
        os.path.join(getattr(sys, "_MEIPASS", ""), "bin", "ffprobe.exe")
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return "ffprobe"


# Sunoアクセス用の標準ヘッダー
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://suno.com/"
}

# UUID抽出用の正規表現パターン
UUID_PATTERN = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)

# 短縮共有URL（例: https://suno.com/s/CgEpfvk5PAbzzdgy）のパターン
SHORT_URL_PATTERN = re.compile(r'https?://(?:www\.)?suno\.com/s/[a-zA-Z0-9]+', re.IGNORECASE)

# 無効なダミー音源や無音ファイルを除外するパターン（SunoのWebオーディオ初期化用sil-100.mp3等）
DUMMY_AUDIO_PATTERN = re.compile(r'(?:sil-\d+|silence|dummy|blank|preview-snippet|static/audio)', re.IGNORECASE)


def fetch_decryption_keys(uuid: str) -> tuple[bytes, bytes] | None:
    """
    SunoのストリーミングライセンスAPIから復号鍵とカウンターIVを取得します。
    (content_key, content_iv) を返します。失敗時はNoneを返します。
    ※本家の正規ダウンロードボタン（クレジット消費）とは無関係の匿名ストリーミング用鍵APIです。
    """
    license_endpoints = [
        "https://studio-api.prod.suno.com/api/mango/rights",
        "https://studio-api-prod.suno.com/api/mango/rights"
    ]
    headers = {
        "User-Agent": DEFAULT_HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Referer": f"https://suno.com/song/{uuid}",
        "Origin": "https://suno.com"
    }
    payload = {
        "content_params": {
            "content_id": uuid,
            "content_type": "clip"
        }
    }

    for ep in license_endpoints:
        try:
            r = requests.post(ep, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                data = r.json()
                glt = data.get("glt")
                key_b64 = data.get("key")
                iv_b64 = data.get("iv")
                if glt and key_b64 and iv_b64:
                    user_key = hashlib.sha256(glt.encode('utf-8')).digest()
                    wrapped_key = base64.b64decode(key_b64)
                    wrapped_iv = base64.b64decode(iv_b64)
                    aad = uuid.encode('utf-8')
                    aesgcm = AESGCM(user_key)
                    content_key = aesgcm.decrypt(wrapped_key[:12], wrapped_key[12:], aad)
                    content_iv = aesgcm.decrypt(wrapped_iv[:12], wrapped_iv[12:], aad)
                    return content_key, content_iv
        except Exception as e:
            print(f"[{uuid}] ライセンスサーバー取得試行エラー ({ep}): {e}")

    return None


def try_decrypt_audio_file(filepath: str, uuid: str) -> bool:
    """
    指定されたファイルが暗号化ストリームの場合、AES-128-CTRで復号して上書き保存します。
    成功した場合はTrue、復号不要または失敗時はFalseを返します。
    """
    if not os.path.exists(filepath):
        return False

    with open(filepath, "rb") as f:
        header = f.read(16)

    # 既に正常なmp4/m4a（ftyp）またはmp3（ID3/0xFF）なら復号不要
    if b"ftyp" in header or header.startswith(b"ID3") or header.startswith(b"\xff\xfb") or header.startswith(b"OggS"):
        return False

    keys = fetch_decryption_keys(uuid)
    if not keys:
        return False

    content_key, content_iv = keys
    try:
        with open(filepath, "rb") as f:
            encrypted_data = f.read()

        cipher = Cipher(algorithms.AES(content_key), modes.CTR(content_iv))
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(encrypted_data) + decryptor.finalize()

        with open(filepath, "wb") as f:
            f.write(decrypted_data)
        print(f"[{uuid}] 暗号化ストリームの自動復号に成功しました！(サイズ: {len(decrypted_data)} bytes)")
        return True
    except Exception as e:
        print(f"[{uuid}] 音声データの復号処理エラー: {e}")
        return False


def resolve_short_url(short_url: str) -> str | None:
    """
    Sunoの短縮共有URL（suno.com/s/...）にアクセスし、本設の楽曲UUIDを解決・取得します。
    """
    try:
        resp = requests.get(short_url, headers=DEFAULT_HEADERS, allow_redirects=True, timeout=12)
        m_url = UUID_PATTERN.search(resp.url)
        if m_url:
            return m_url.group(0).lower()

        soup = BeautifulSoup(resp.text, "html.parser")
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            m_canon = UUID_PATTERN.search(canonical["href"])
            if m_canon:
                return m_canon.group(0).lower()

        m_text = UUID_PATTERN.search(resp.text)
        if m_text:
            return m_text.group(0).lower()

    except Exception as e:
        print(f"短縮URLの解決エラー ({short_url}): {e}")
    return None


def extract_uuids(text: str) -> list[str]:
    """
    入力されたテキスト（通常URL、短縮URL、UUID直打ち）からSunoの楽曲UUIDを抽出し、重複を排除して返します。
    """
    unique_uuids = []
    seen = set()

    # 1. 通常のUUIDパターン（URL内や直打ち）を抽出
    direct_uuids = UUID_PATTERN.findall(text)
    for item in direct_uuids:
        lower_item = item.lower()
        if lower_item not in seen:
            seen.add(lower_item)
            unique_uuids.append(lower_item)

    # 2. 短縮URL（https://suno.com/s/...）を抽出して解決
    short_urls = SHORT_URL_PATTERN.findall(text)
    for s_url in short_urls:
        resolved_uuid = resolve_short_url(s_url)
        if resolved_uuid and resolved_uuid not in seen:
            seen.add(resolved_uuid)
            unique_uuids.append(resolved_uuid)

    return unique_uuids


def sanitize_filename(name: str) -> str:
    """
    Windowsのファイル名として使えない禁止文字を安全な文字に置換します。
    """
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', name)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned if cleaned else "track"


def extract_audio_candidates_from_text(text: str, uuid: str) -> list[str]:
    """
    SunoページのHTMLや埋め込みデータから音源URL候補を抽出し、
    無音ダミーファイルを除外した上で優先順位をつけて返します。
    """
    uuid_lower = uuid.lower()
    high_priority = []
    normal_priority = []
    seen = set()

    def add_candidate(u: str):
        if not u or not isinstance(u, str):
            return
        u = u.strip().replace("\\u0026", "&").replace("&amp;", "&")
        if u.startswith("//"):
            u = "https:" + u
        # アクセス禁止APIや無音ダミー音源（sil-100.mp3など）を徹底除外
        if "forbidden" in u.lower() or DUMMY_AUDIO_PATTERN.search(u):
            return
        if u in seen:
            return
        seen.add(u)

        # 該当UUIDが含まれているURLは最優先（本物の個別曲ストリーム）
        if uuid_lower in u.lower():
            high_priority.append(u)
        else:
            normal_priority.append(u)

    # 1. media_urls のJSON配列構造を最優先探索（最新の高音質ストリーム）
    media_url_blocks = re.findall(r'"media_urls"\s*:\s*(\[[^\]]+\])', text)
    for block in media_url_blocks:
        urls = re.findall(r'"url"\s*:\s*"([^"]+)"', block)
        for u in urls:
            add_candidate(u)

    # 2. 安定して高品質フル音源を提供する公式CDNストリーム
    add_candidate(f"https://cdn1.suno.ai/{uuid}.mp4")

    # 3. audio_url フィールドからの抽出
    m_audio = re.findall(r'"audio_url"\s*:\s*"([^"]+)"', text)
    for u in m_audio:
        add_candidate(u)

    # 4. 直接の音声配信URLパターン（m4a, mp3, mp4等）を正規表現で探索
    direct_urls = re.findall(r'(https?://[^\s"\'<>]+\.(?:m4a|mp3|mp4)(?:\?[^\s"\'<>]*)?)', text)
    for u in direct_urls:
        add_candidate(u)

    # 5. 代替CDNフォールバックURL
    fallback_urls = [
        f"https://cdn1.suno.ai/{uuid}.mp3",
        f"https://audiopipe.suno.ai/?item_id={uuid}"
    ]
    for u in fallback_urls:
        add_candidate(u)

    return high_priority + normal_priority


def fetch_song_metadata(uuid: str) -> dict:
    """
    Sunoの楽曲ページからタイトル、アーティスト、カバー画像、音源URL候補を取得します。
    """
    page_url = f"https://suno.com/song/{uuid}"
    embed_url = f"https://suno.com/embed/{uuid}"
    title = f"Suno Track {uuid[:8]}"
    artist = "Suno AI"
    image_url = f"https://cdn2.suno.ai/image_large_{uuid}.jpeg"
    audio_candidates = []

    # 1. songページからメタデータと音源URLを探索
    try:
        resp = requests.get(page_url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code == 404:
            title = f"【存在しない楽曲】({uuid[:8]})"
        elif resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")

            # タイトルとアーティストのパース
            page_title = soup.title.string if soup.title else ""
            if page_title:
                page_title = html.unescape(page_title.strip())
                m = re.match(r'^(.*?)\s+by\s+(.*?)(?:\s*\|\s*Suno)?$', page_title, re.IGNORECASE)
                if m:
                    extracted_title = m.group(1).strip()
                    extracted_artist = m.group(2).strip()
                    if extracted_title:
                        title = extracted_title
                    if extracted_artist:
                        artist = extracted_artist

            # OpenGraphタグからの補完
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                candidate_title = html.unescape(og_title["content"].strip())
                if candidate_title and title.startswith("Suno Track"):
                    title = candidate_title

            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = og_image["content"].strip()

            # descriptionメタタグからのアーティスト補完
            desc_meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", property="og:description")
            if desc_meta and desc_meta.get("content"):
                desc_text = html.unescape(desc_meta["content"].strip())
                m_artist = re.search(r'by\s+([^\(@]+?)(?:\s*\(@|\.|$)', desc_text)
                if m_artist and artist == "Suno AI":
                    found_artist = m_artist.group(1).strip()
                    if found_artist:
                        artist = found_artist

            # 音源URL候補の抽出
            audio_candidates.extend(extract_audio_candidates_from_text(resp.text, uuid))

    except Exception as e:
        print(f"[{uuid}] メタデータ取得エラー (songページ): {e}")

    # 2. embedページからも探索（非公開楽曲や埋め込みデータ対応）
    has_valid_stream = any("cdn1.suno.ai" not in u and "audiopipe" not in u for u in audio_candidates)
    if not has_valid_stream:
        try:
            r_embed = requests.get(embed_url, headers=DEFAULT_HEADERS, timeout=12)
            if r_embed.status_code == 200:
                embed_candidates = extract_audio_candidates_from_text(r_embed.text, uuid)
                for u in embed_candidates:
                    if u not in audio_candidates:
                        audio_candidates.append(u)
        except Exception as e:
            print(f"[{uuid}] メタデータ取得エラー (embedページ): {e}")

    # フォールバックの担保
    if not audio_candidates:
        audio_candidates = [
            f"https://cdn1.suno.ai/{uuid}.mp4",
            f"https://cdn1.suno.ai/{uuid}.mp3",
            f"https://audiopipe.suno.ai/?item_id={uuid}"
        ]

    primary_audio_url = audio_candidates[0]

    return {
        "uuid": uuid,
        "title": title,
        "artist": artist,
        "image_url": image_url,
        "audio_url": primary_audio_url,
        "candidate_urls": audio_candidates,
        "page_url": page_url
    }


def download_artwork(image_url: str) -> bytes:
    """
    カバーアート画像（JPEG/PNG等）をバイナリとしてダウンロードします。
    """
    try:
        r = requests.get(image_url, headers=DEFAULT_HEADERS, timeout=15)
        if r.status_code == 200:
            return r.content
    except Exception as e:
        print(f"アートワーク取得失敗 ({image_url}): {e}")
    return b""


def normalize_artwork(image_bytes: bytes) -> tuple[bytes, str]:
    """
    アートワーク画像をRGB形式の標準JPEG（最大1000x1000）に正規化し、
    Windows Media Player、iTunes、カーナビ、スマートフォン等との互換性を確保します。
    (画像バイナリ, MIMEタイプ) を返します。
    """
    if not image_bytes:
        return b"", "image/jpeg"
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                canvas = Image.new("RGB", img.size, (255, 255, 255))
                converted = img.convert("RGBA")
                canvas.paste(converted, mask=converted.split()[3])
                img = canvas
            elif img.mode != "RGB":
                img = img.convert("RGB")

            img.thumbnail((1000, 1000), Image.Resampling.LANCZOS)
            out = BytesIO()
            img.save(out, format="JPEG", quality=92, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"アートワーク画像の正規化エラー: {e}")
        return image_bytes, "image/jpeg"


def verify_audio_file(filepath: str, min_duration_sec: float = 3.0, min_bytes: int = 50 * 1024) -> tuple[bool, float, str]:
    """
    ダウンロードしたファイルが本物の音声データであり、十分な再生時間（デフォルト3秒以上）と
    ファイルサイズ（デフォルト50KB以上）を持っているかffprobeで検証します。
    (検証OKか, 再生秒数, メッセージ) を返します。
    """
    if not os.path.exists(filepath):
        return False, 0.0, "ファイルが存在しません"

    file_size = os.path.getsize(filepath)
    if file_size < min_bytes:
        return False, 0.0, f"ファイルサイズが小さすぎます ({file_size} bytes < {min_bytes} bytes)"

    try:
        cmd = [
            get_ffprobe_path(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            filepath
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        if res.returncode != 0:
            return False, 0.0, f"ffprobeの解析に失敗しました: {res.stderr.strip()}"

        output = res.stdout.strip()
        duration = float(output) if output else 0.0
        if duration < min_duration_sec:
            return False, duration, f"再生時間が短すぎます（{duration:.2f}秒 < {min_duration_sec}秒: 無音またはダミー音源の可能性）"

        return True, duration, "OK"
    except Exception as e:
        print(f"ffprobeによる音声検証エラー: {e}")
        if file_size >= 200 * 1024:
            return True, 0.0, "サイズ確認により通過"
        return False, 0.0, str(e)


def download_audio_from_candidates(uuid: str, candidates: list[str], tmpdir: str) -> tuple[str, str]:
    """
    候補URLを優先順に試行し、正常な音声データであることをffprobeで厳格に検証した上で
    ローカルファイルに保存します。暗号化されている場合は自動復号します。
    (保存ファイルパス, 成功URL) を返します。
    """
    last_error = None
    for url in candidates:
        try:
            print(f"[{uuid}] 音源ダウンロード試行中: {url}")
            resp = requests.get(url, headers=DEFAULT_HEADERS, stream=True, timeout=30)
            if resp.status_code == 200:
                lower_url = url.lower().split("?")[0]
                if lower_url.endswith(".mp3"):
                    ext = ".mp3"
                elif lower_url.endswith(".mp4"):
                    ext = ".mp4"
                elif lower_url.endswith(".opus"):
                    ext = ".opus"
                else:
                    ext = ".m4a"

                target_file = os.path.join(tmpdir, f"{uuid}_source{ext}")

                first_chunk = None
                with open(target_file, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            if first_chunk is None:
                                first_chunk = chunk
                                if (chunk.strip().startswith(b"<!DOCTYPE") or
                                    chunk.strip().startswith(b"<html") or
                                    chunk.strip().startswith(b"<?xml") or
                                    chunk.strip().startswith(b"{\"")):
                                    raise RuntimeError("返却されたデータが音声ファイルではなくHTML/XML/JSONです")
                            f.write(chunk)

                # 1. 音声データの完全性・再生時間（Duration）チェック
                is_valid, duration, reason = verify_audio_file(target_file)
                if not is_valid:
                    # 2. 暗号化ストリーム（AES-128-CTR）の自動復号を試行
                    print(f"[{uuid}] 通常の音声解析に失敗 ({reason})。暗号化ストリームの自動復号を試行します...")
                    if try_decrypt_audio_file(target_file, uuid):
                        is_valid, duration, reason = verify_audio_file(target_file)

                if is_valid:
                    print(f"[{uuid}] 音源取得＆検証成功: {url} ({os.path.getsize(target_file)} bytes, 再生時間: {duration:.1f}秒, 形式: {ext})")
                    return target_file, url
                else:
                    print(f"[{uuid}] 音源データが無効と判定されました ({reason})。次の候補を試行します: {url}")
                    last_error = reason
                    if os.path.exists(target_file):
                        try:
                            os.remove(target_file)
                        except OSError:
                            pass
            else:
                print(f"[{uuid}] アクセス拒否または未検出（ステータスコード: {resp.status_code}）: {url}")
                last_error = f"ステータスコード {resp.status_code}"
        except Exception as e:
            print(f"[{uuid}] ダウンロード試行失敗 ({url}): {e}")
            last_error = str(e)

    raise RuntimeError(f"すべての候補URLからの音源取得に失敗しました（最後のエラー: {last_error}）。楽曲が非公開になっているか、URLが正しくない可能性があります。")



def process_song_download(
    uuid: str,
    title: str,
    artist: str,
    image_url: str,
    format_type: str,
    output_dir: str,
    audio_url: str = None,
    candidate_urls: list = None
) -> dict:
    """
    音源をダウンロードし、選択した形式（MP3またはM4A）に変換して、
    公式アートワークとメタデータを埋め込みます。
    """
    os.makedirs(output_dir, exist_ok=True)
    format_type = format_type.lower()
    if format_type not in ["mp3", "m4a"]:
        format_type = "mp3"

    # 出力ファイル名の生成
    safe_artist = sanitize_filename(artist)
    safe_title = sanitize_filename(title)
    base_filename = f"{safe_artist} - {safe_title}"
    output_filename = f"{base_filename}.{format_type}"
    target_path = os.path.join(output_dir, output_filename)

    # 同名ファイルが存在する場合は連番を付与
    counter = 1
    while os.path.exists(target_path):
        output_filename = f"{base_filename} ({counter}).{format_type}"
        target_path = os.path.join(output_dir, output_filename)
        counter += 1

    # 試行候補URLリストの組み立て
    candidates = []
    if audio_url and not DUMMY_AUDIO_PATTERN.search(audio_url) and "forbidden" not in audio_url.lower():
        candidates.append(audio_url)
    if candidate_urls:
        for u in candidate_urls:
            if u not in candidates and not DUMMY_AUDIO_PATTERN.search(u) and "forbidden" not in u.lower():
                candidates.append(u)

    # 候補が空、あるいは旧来URLのみの場合は最新のメタデータを再問い合わせて最新URLを補完
    if not candidates or all("cdn1.suno.ai" in u for u in candidates):
        refreshed = fetch_song_metadata(uuid)
        for u in refreshed.get("candidate_urls", []):
            if u not in candidates and not DUMMY_AUDIO_PATTERN.search(u) and "forbidden" not in u.lower():
                candidates.append(u)

    # 一時作業用ディレクトリ
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_audio = os.path.join(tmpdir, f"{uuid}_converted.{format_type}")

        # 1. 音源のダウンロード（再生時間とファイルサイズを厳格検証）
        temp_source, success_url = download_audio_from_candidates(uuid, candidates, tmpdir)

        # 2. アートワーク画像の取得と互換性正規化（RGB JPEG化）
        raw_artwork = download_artwork(image_url)
        if not raw_artwork:
            fallback_img = f"https://cdn2.suno.ai/image_large_{uuid}.jpeg"
            raw_artwork = download_artwork(fallback_img)
        artwork_bytes, artwork_mime = normalize_artwork(raw_artwork)

        # 3. FFmpegによる音声抽出 / 変換（タイムスタンプ同期補正と業界標準44.1kHzへのリサンプリングで音飛び防止）
        ffmpeg_bin = get_ffmpeg_path()
        if format_type == "m4a":
            cmd = [
                ffmpeg_bin, "-y", "-i", temp_source,
                "-vn", "-sn", "-dn",
                "-map_metadata", "-1",
                "-c:a", "aac",
                "-b:a", "320k",
                "-ar", "44100",
                "-af", "aresample=44100:async=1:first_pts=0",
                temp_audio
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"FFmpegによるM4A変換に失敗しました: {res.stderr.strip()}")
        else:
            cmd = [
                ffmpeg_bin, "-y", "-i", temp_source,
                "-vn", "-sn", "-dn",
                "-map_metadata", "-1",
                "-c:a", "libmp3lame",
                "-b:a", "320k",
                "-ar", "44100",
                "-af", "aresample=44100:async=1:first_pts=0",
                temp_audio
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode != 0:
                raise RuntimeError(f"FFmpegによるMP3変換に失敗しました: {res.stderr.strip()}")


        # 4. メタデータ＆アートワークの埋め込み
        if format_type == "m4a":
            # M4A（MP4コンテナ）用タグ埋め込み
            m4a = MP4(temp_audio)
            m4a["\xa9nam"] = [title]
            m4a["\xa9ART"] = [artist]
            m4a["\xa9alb"] = ["Suno AI"]
            if artwork_bytes:
                m4a["covr"] = [MP4Cover(artwork_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            m4a.save()
        else:
            # MP3用ID3v2タグ埋め込み
            try:
                mp3 = MP3(temp_audio, ID3=ID3)
                mp3.add_tags()
            except Exception:
                mp3 = MP3(temp_audio, ID3=ID3)

            mp3.tags.add(TIT2(encoding=3, text=title))
            mp3.tags.add(TPE1(encoding=3, text=artist))
            mp3.tags.add(TALB(encoding=3, text="Suno AI"))
            if artwork_bytes:
                mp3.tags.add(APIC(
                    encoding=3,
                    mime=artwork_mime,
                    type=3,  # フロントカバー
                    desc="Cover",
                    data=artwork_bytes
                ))
            mp3.save(v2_version=3)

        # 5. 完成ファイルを保存先へ移動
        with open(temp_audio, "rb") as src, open(target_path, "wb") as dst:
            dst.write(src.read())

    return {
        "uuid": uuid,
        "filename": output_filename,
        "filepath": os.path.abspath(target_path),
        "filesize": os.path.getsize(target_path),
        "format": format_type
    }

