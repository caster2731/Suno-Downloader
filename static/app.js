// ==========================================================================
// Suno Downloader - フロントエンドロジック
// ==========================================================================

// アプリケーション状態
const state = {
  songs: [],
  currentAudio: null,
  currentPlayingUuid: null,
  defaultDownloadDir: "",
  isDownloadingAll: false
};

// サンプルURL（動作確認用）
const SAMPLE_URLS = [
  "https://suno.com/song/2e0eec9e-4f86-46c5-9a43-508829fb9d0b",
  "https://suno.com/song/7b30e35a-f3d0-4340-9087-26b0db791ffa"
];

// DOM要素
const urlInput = document.getElementById("url-input");
const btnFetch = document.getElementById("btn-fetch");
const btnFetchText = document.getElementById("btn-fetch-text");
const btnSample = document.getElementById("btn-sample");
const btnClearInput = document.getElementById("btn-clear-input");
const btnOpenFolder = document.getElementById("btn-open-folder");
const destPathDisplay = document.getElementById("dest-path-display");
const resultsSection = document.getElementById("results-section");
const songCountBadge = document.getElementById("song-count-badge");
const songsList = document.getElementById("songs-list");
const btnDownloadAll = document.getElementById("btn-download-all");
const btnClearAll = document.getElementById("btn-clear-all");
const batchProgressContainer = document.getElementById("batch-progress-container");
const batchProgressBar = document.getElementById("batch-progress-bar");
const batchProgressStatus = document.getElementById("batch-progress-status");
const batchProgressPercent = document.getElementById("batch-progress-percent");
const toastContainer = document.getElementById("toast-container");

// --- 初期化 ---
document.addEventListener("DOMContentLoaded", () => {
  loadConfig();
  bindEvents();
});

// サーバー設定の取得
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const data = await res.json();
      state.defaultDownloadDir = data.default_download_dir;
      destPathDisplay.textContent = data.default_download_dir;
    }
  } catch (err) {
    console.error("設定取得エラー:", err);
    destPathDisplay.textContent = "./downloads";
  }
}

// イベントリスナーのバインド
function bindEvents() {
  // サンプルURL挿入
  btnSample.addEventListener("click", () => {
    urlInput.value = SAMPLE_URLS.join("\n");
    showToast("サンプルURLを入力しました。「楽曲情報を取得する」を押してください。", "info");
  });

  // 入力クリア
  btnClearInput.addEventListener("click", () => {
    urlInput.value = "";
    urlInput.focus();
  });

  // メタデータ取得ボタン
  btnFetch.addEventListener("click", handleFetchMetadata);

  // 保存先フォルダを開く
  btnOpenFolder.addEventListener("click", () => {
    openFolder();
  });
  destPathDisplay.addEventListener("click", () => {
    openFolder();
  });

  // 全て一括ダウンロード
  btnDownloadAll.addEventListener("click", handleDownloadAll);

  // 全てクリア
  btnClearAll.addEventListener("click", () => {
    stopCurrentAudio();
    state.songs = [];
    renderSongs();
    showToast("リストをクリアしました", "info");
  });

  // グローバル形式変更
  document.querySelectorAll('input[name="global-format"]').forEach(radio => {
    radio.addEventListener("change", (e) => {
      const newFmt = e.target.value;
      state.songs.forEach(song => {
        if (!song.completed) {
          song.format = newFmt;
        }
      });
      renderSongs();
      showToast(`一括ダウンロード形式を [${newFmt.toUpperCase()}] に設定しました`, "info");
    });
  });
}

// 選択中のグローバル形式を取得
function getGlobalFormat() {
  const checked = document.querySelector('input[name="global-format"]:checked');
  return checked ? checked.value : "mp3";
}

// --- 楽曲情報取得処理 ---
async function handleFetchMetadata() {
  const text = urlInput.value.trim();
  if (!text) {
    showToast("URLを入力してください。", "error");
    urlInput.focus();
    return;
  }

  // ローディング表示
  btnFetch.disabled = true;
  btnFetchText.textContent = "解析・情報取得中...";
  btnFetch.querySelector("svg")?.classList.add("spinning");

  try {
    const res = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "URLの解析に失敗しました。");
    }

    if (!data.songs || data.songs.length === 0) {
      showToast("有効なSunoの楽曲URLが見つかりませんでした。", "error");
      return;
    }

    // 重複を避けてリストに追加
    const currentGlobalFmt = getGlobalFormat();
    let addedCount = 0;

    data.songs.forEach(newSong => {
      const exists = state.songs.some(s => s.uuid === newSong.uuid);
      if (!exists) {
        state.songs.push({
          ...newSong,
          format: currentGlobalFmt,
          status: "waiting", // waiting | downloading | success | error
          statusText: "待機中",
          fileInfo: null,
          completed: false
        });
        addedCount++;
      }
    });

    renderSongs();
    showToast(`${addedCount}曲の情報を取得しました！`, "success");
    urlInput.value = ""; // 入力欄をクリア

  } catch (err) {
    showToast(err.message || "通信エラーが発生しました。", "error");
  } finally {
    btnFetch.disabled = false;
    btnFetchText.textContent = "楽曲情報を取得する";
    btnFetch.querySelector("svg")?.classList.remove("spinning");
  }
}

// --- リストの描画 ---
function renderSongs() {
  if (state.songs.length === 0) {
    resultsSection.style.display = "none";
    return;
  }

  resultsSection.style.display = "block";
  songCountBadge.textContent = `${state.songs.length} 曲`;
  songsList.innerHTML = "";

  state.songs.forEach((song, idx) => {
    const card = document.createElement("div");
    card.className = "song-card";
    card.id = `song-card-${song.uuid}`;

    const isPlaying = state.currentPlayingUuid === song.uuid;

    card.innerHTML = `
      <!-- アートワークと試聴ボタン -->
      <div class="art-preview-wrapper">
        <img src="${escapeHtml(song.image_url)}" alt="ジャケット画像" class="art-img" onerror="this.src='https://cdn1.suno.ai/2221549b.png'">
        <button class="play-overlay-btn ${isPlaying ? 'is-playing' : ''}" onclick="togglePlayPreview('${song.uuid}', '${escapeHtml(song.audio_url)}')">
          <div class="play-icon-circle">
            ${isPlaying ? `
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <rect x="6" y="4" width="4" height="16"></rect>
                <rect x="14" y="4" width="4" height="16"></rect>
              </svg>
            ` : `
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
            `}
          </div>
        </button>
      </div>

      <!-- 楽曲情報（タイトル・アーティスト編集欄） -->
      <div class="song-details">
        <div class="field-row">
          <span class="field-label">曲名</span>
          <input type="text" class="field-input" value="${escapeHtml(song.title)}" 
            onchange="updateSongField('${song.uuid}', 'title', this.value)"
            ${song.completed ? 'disabled' : ''}>
        </div>
        <div class="field-row">
          <span class="field-label">アーティスト</span>
          <input type="text" class="field-input" value="${escapeHtml(song.artist)}" 
            onchange="updateSongField('${song.uuid}', 'artist', this.value)"
            ${song.completed ? 'disabled' : ''}>
        </div>
        <div class="song-meta-footer">
          <span class="uuid-tag">${song.uuid.substring(0, 8)}...</span>
          <a href="${escapeHtml(song.page_url)}" target="_blank" rel="noopener noreferrer" class="suno-link">
            公式ページ
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
              <polyline points="15 3 21 3 21 9"></polyline>
              <line x1="10" y1="14" x2="21" y2="3"></line>
            </svg>
          </a>
        </div>
      </div>

      <!-- 操作エリア -->
      <div class="song-actions">
        <span class="status-badge status-${song.status}" id="status-badge-${song.uuid}">
          ${getStatusIcon(song.status)}
          <span>${escapeHtml(song.statusText)}</span>
        </span>

        <div class="card-button-group">
          ${song.completed ? `
            <a href="/api/download-file?filepath=${encodeURIComponent(song.fileInfo.filepath)}" class="btn btn-ghost btn-sm" title="ブラウザでダウンロード">
              保存
            </a>
          ` : `
            <select class="field-input" style="width: auto; padding: 4px 8px; font-size: 0.85rem;" onchange="updateSongField('${song.uuid}', 'format', this.value)">
              <option value="mp3" ${song.format === 'mp3' ? 'selected' : ''}>MP3</option>
              <option value="m4a" ${song.format === 'm4a' ? 'selected' : ''}>M4A</option>
            </select>
            <button class="btn btn-primary btn-sm" onclick="downloadSingle('${song.uuid}')">
              ダウンロード
            </button>
          `}
          <button class="btn-icon-danger" title="削除" onclick="removeSong('${song.uuid}')">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      </div>
    `;

    songsList.appendChild(card);
  });
}

// ステータスアイコン
function getStatusIcon(status) {
  if (status === "downloading") {
    return `<svg class="spinning" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M12 2a10 10 0 0 1 10 10"></path></svg>`;
  } else if (status === "success") {
    return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
  } else if (status === "error") {
    return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`;
  }
  return `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`;
}

// 楽曲プロパティの更新
window.updateSongField = function(uuid, field, value) {
  const song = state.songs.find(s => s.uuid === uuid);
  if (song) {
    song[field] = value.trim();
  }
};

// リストから1曲削除
window.removeSong = function(uuid) {
  if (state.currentPlayingUuid === uuid) {
    stopCurrentAudio();
  }
  state.songs = state.songs.filter(s => s.uuid !== uuid);
  renderSongs();
};

// --- 単一曲のダウンロード ---
window.downloadSingle = async function(uuid) {
  const song = state.songs.find(s => s.uuid === uuid);
  if (!song || song.completed) return;

  song.status = "downloading";
  song.statusText = "ダウンロード・変換中...";
  updateCardStatus(song);

  try {
    const res = await fetch("/api/download-single", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        uuid: song.uuid,
        title: song.title,
        artist: song.artist,
        image_url: song.image_url,
        format: song.format,
        output_dir: state.defaultDownloadDir,
        audio_url: song.audio_url,
        candidate_urls: song.candidate_urls
      })
    });

    const data = await res.json();
    if (!res.ok || data.status === "error") {
      throw new Error(data.message || "ダウンロードに失敗しました。");
    }

    song.status = "success";
    const mbSize = (data.data.filesize / (1024 * 1024)).toFixed(1);
    song.statusText = `完了 (${mbSize} MB)`;
    song.fileInfo = data.data;
    song.completed = true;

    showToast(`「${song.title}」の保存が完了しました！`, "success");

  } catch (err) {
    song.status = "error";
    song.statusText = "エラー";
    showToast(`「${song.title}」のダウンロード失敗: ${err.message}`, "error");
  } finally {
    renderSongs();
  }
};

// カードのステータス表示のみを高速更新
function updateCardStatus(song) {
  const badge = document.getElementById(`status-badge-${song.uuid}`);
  if (badge) {
    badge.className = `status-badge status-${song.status}`;
    badge.innerHTML = `${getStatusIcon(song.status)} <span>${escapeHtml(song.statusText)}</span>`;
  }
}

// --- 一括ダウンロード処理 ---
async function handleDownloadAll() {
  if (state.isDownloadingAll) return;
  const pendingSongs = state.songs.filter(s => !s.completed);

  if (pendingSongs.length === 0) {
    showToast("ダウンロード対象の楽曲がありません。", "info");
    return;
  }

  state.isDownloadingAll = true;
  btnDownloadAll.disabled = true;
  batchProgressContainer.style.display = "block";

  let successCount = 0;
  const total = pendingSongs.length;

  for (let i = 0; i < total; i++) {
    const song = pendingSongs[i];
    const percent = Math.round(((i) / total) * 100);

    batchProgressBar.style.width = `${percent}%`;
    batchProgressPercent.textContent = `${percent}%`;
    batchProgressStatus.textContent = `[${i + 1}/${total}] 「${song.title}」を処理中...`;

    await downloadSingle(song.uuid);
    if (song.completed) {
      successCount++;
    }
  }

  // 完了
  batchProgressBar.style.width = "100%";
  batchProgressPercent.textContent = "100%";
  batchProgressStatus.textContent = `一括ダウンロード完了！ (${successCount}/${total} 曲)`;

  state.isDownloadingAll = false;
  btnDownloadAll.disabled = false;

  showToast(`一括ダウンロードが完了しました！（${successCount}曲保存）`, "success");
}

// --- 試聴用プレイヤー制御 ---
window.togglePlayPreview = function(uuid, audioUrl) {
  if (state.currentPlayingUuid === uuid) {
    stopCurrentAudio();
    renderSongs();
    return;
  }

  stopCurrentAudio();

  state.currentAudio = new Audio(audioUrl);
  state.currentPlayingUuid = uuid;

  state.currentAudio.addEventListener("ended", () => {
    stopCurrentAudio();
    renderSongs();
  });

  state.currentAudio.addEventListener("error", (e) => {
    console.error("再生エラー:", e);
    showToast("試聴音源の再生に失敗しました。", "error");
    stopCurrentAudio();
    renderSongs();
  });

  state.currentAudio.play().catch(e => {
    console.warn("自動再生制限またはエラー:", e);
    showToast("音声の再生がブロックされました。ブラウザの権限を確認してください。", "error");
    stopCurrentAudio();
    renderSongs();
  });

  renderSongs();
};

function stopCurrentAudio() {
  if (state.currentAudio) {
    state.currentAudio.pause();
    state.currentAudio = null;
  }
  state.currentPlayingUuid = null;
}

// --- 保存先フォルダを開く ---
async function openFolder() {
  try {
    const res = await fetch("/api/open-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder_path: state.defaultDownloadDir })
    });
    const data = await res.json();
    if (res.ok) {
      showToast("保存先フォルダを開きました", "info");
    } else {
      showToast(data.detail || "フォルダを開けませんでした", "error");
    }
  } catch (err) {
    showToast("フォルダ起動エラー: " + err.message, "error");
  }
}

// --- トースト通知 ---
function showToast(message, type = "info") {
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.innerHTML = `
    <span>${escapeHtml(message)}</span>
  `;

  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(40px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// HTMLエスケープヘルパー
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
