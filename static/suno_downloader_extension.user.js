// ==UserScript==
// @name         Suno Downloader - ワークスペース＆楽曲連携アシスタント
// @namespace    https://github.com/caster2731/Suno-Downloader
// @version      1.0.0
// @description  Sunoのワークスペースや楽曲一覧から、選択した楽曲を一括で「Suno Downloader」へ直接転送・ダウンロードします。
// @author       Suno Downloader
// @match        https://suno.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_notification
// @grant        GM_getValue
// @grant        GM_setValue
// @connect      127.0.0.1
// @connect      localhost
// @run-at       document-end
// ==/UserScript==

(function () {
  'use strict';

  // APIサーバーURL
  const API_BASE = "http://127.0.0.1:8000";

  // UUID判定用正規表現
  const UUID_REGEX = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

  // 内部状態
  const state = {
    selectedUuids: new Set(),
    autoDownload: true,
    format: "mp3",
    serverOnline: false
  };

  // --- スタイル定義 ---
  const style = document.createElement("style");
  style.textContent = `
    /* Suno Downloader フローティングバー */
    #suno-dl-bar {
      position: fixed;
      bottom: 96px; /* Sunoのフッター再生バー（約80px）の真上に浮かせる初期位置 */
      right: 24px;
      z-index: 9999999; /* プレイヤーや他のUIに隠れない最前面表示 */
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 10px 18px;
      background: rgba(18, 18, 26, 0.94);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 9999px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.7), 0 0 24px rgba(139, 92, 246, 0.35);
      color: #fff;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 13px;
      user-select: none;
      transition: opacity 0.3s ease, transform 0.3s ease;
    }
    #suno-dl-bar.is-dragging {
      opacity: 0.88;
      box-shadow: 0 14px 40px rgba(0, 0, 0, 0.85), 0 0 32px rgba(139, 92, 246, 0.6);
      transition: none;
    }
    .suno-dl-drag-handle {
      cursor: grab;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 8px;
      border-radius: 9999px;
      background: rgba(139, 92, 246, 0.18);
      border: 1px solid rgba(139, 92, 246, 0.3);
      color: #c4b5fd;
      font-weight: 700;
      transition: all 0.2s;
    }
    .suno-dl-drag-handle:hover {
      background: rgba(139, 92, 246, 0.35);
      color: #fff;
    }
    .suno-dl-drag-handle:active {
      cursor: grabbing;
    }
    #suno-dl-bar.hidden {
      opacity: 0;
      transform: translateY(20px);
      pointer-events: none;
    }
    #suno-dl-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 22px;
      height: 22px;
      padding: 0 6px;
      background: linear-gradient(135deg, #ec4899, #8b5cf6);
      border-radius: 11px;
      font-weight: 700;
      font-size: 12px;
      color: #fff;
    }
    .suno-dl-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 9999px;
      border: none;
      cursor: pointer;
      font-size: 13px;
      font-weight: 600;
      transition: all 0.2s;
    }
    .suno-dl-btn-primary {
      background: linear-gradient(135deg, #8b5cf6, #ec4899);
      color: #fff;
      box-shadow: 0 2px 10px rgba(139, 92, 246, 0.4);
    }
    .suno-dl-btn-primary:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 14px rgba(139, 92, 246, 0.6);
    }
    .suno-dl-btn-secondary {
      background: rgba(255, 255, 255, 0.1);
      color: #e2e8f0;
    }
    .suno-dl-btn-secondary:hover {
      background: rgba(255, 255, 255, 0.2);
    }
    /* 各曲カード用の個別DLボタン */
    .suno-dl-item-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      margin-left: 6px;
      border-radius: 50%;
      background: rgba(139, 92, 246, 0.2);
      border: 1px solid rgba(139, 92, 246, 0.4);
      color: #c4b5fd;
      cursor: pointer;
      font-size: 14px;
      transition: all 0.2s;
      vertical-align: middle;
    }
    .suno-dl-item-btn:hover {
      background: #8b5cf6;
      color: #fff;
      transform: scale(1.1);
    }
    /* スクリプト内トースト通知 */
    .suno-dl-toast {
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 99999999;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 12px 20px;
      border-radius: 12px;
      background: #181824;
      border: 1px solid rgba(139, 92, 246, 0.5);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.6);
      color: #fff;
      font-size: 14px;
      animation: sunoDlFadeIn 0.3s ease;
    }
    @keyframes sunoDlFadeIn {
      from { opacity: 0; transform: translateY(-10px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `;
  document.head.appendChild(style);

  // --- フローティングバーの生成 ---
  const bar = document.createElement("div");
  bar.id = "suno-dl-bar";
  bar.innerHTML = `
    <span class="suno-dl-drag-handle" id="suno-dl-drag-handle" title="ドラッグして画面の好きな位置に移動できます">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M10 9h4V6h3l-5-5-5 5h3v3zm-1 1H6V7l-5 5 5 5v-3h3v-4zm14 2l-5-5v3h-3v4h3v3l5-5zm-9 3h-4v3H7l5 5 5-5h-3v-3z"/></svg>
      Suno DL
    </span>
    <span id="suno-dl-badge">0</span>
    <button class="suno-dl-btn suno-dl-btn-primary" id="suno-dl-submit-btn">
      📥 選択した曲をダウンロード
    </button>
    <button class="suno-dl-btn suno-dl-btn-secondary" id="suno-dl-clear-btn" title="選択をすべて解除">
      解除
    </button>
    <label style="display:inline-flex; align-items:center; gap:4px; cursor:pointer; font-size:12px; color:#cbd5e1;">
      <input type="checkbox" id="suno-dl-auto-check" checked style="cursor:pointer;" />
      自動保存
    </label>
  `;
  document.body.appendChild(bar);

  // --- 位置の復元と自由ドラッグ移動 ---
  const savedPos = localStorage.getItem("suno_downloader_bar_pos");
  if (savedPos) {
    try {
      const pos = JSON.parse(savedPos);
      if (typeof pos.left === "number" && typeof pos.top === "number") {
        bar.style.left = `${Math.max(10, Math.min(window.innerWidth - 300, pos.left))}px`;
        bar.style.top = `${Math.max(10, Math.min(window.innerHeight - 80, pos.top))}px`;
        bar.style.right = "auto";
        bar.style.bottom = "auto";
      }
    } catch (e) {
      // 復元失敗時はデフォルト位置
    }
  }

  const dragHandle = bar.querySelector("#suno-dl-drag-handle");
  let isDragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let barStartX = 0;
  let barStartY = 0;

  dragHandle.addEventListener("mousedown", (e) => {
    isDragging = true;
    bar.classList.add("is-dragging");
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    const rect = bar.getBoundingClientRect();
    barStartX = rect.left;
    barStartY = rect.top;

    bar.style.right = "auto";
    bar.style.bottom = "auto";
    bar.style.left = `${barStartX}px`;
    bar.style.top = `${barStartY}px`;

    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isDragging) return;
    const deltaX = e.clientX - dragStartX;
    const deltaY = e.clientY - dragStartY;
    let newX = barStartX + deltaX;
    let newY = barStartY + deltaY;

    // 画面外にはみ出さないよう制限
    newX = Math.max(8, Math.min(window.innerWidth - bar.offsetWidth - 8, newX));
    newY = Math.max(8, Math.min(window.innerHeight - bar.offsetHeight - 8, newY));

    bar.style.left = `${newX}px`;
    bar.style.top = `${newY}px`;
  });

  window.addEventListener("mouseup", () => {
    if (isDragging) {
      isDragging = false;
      bar.classList.remove("is-dragging");
      const rect = bar.getBoundingClientRect();
      localStorage.setItem("suno_downloader_bar_pos", JSON.stringify({
        left: Math.round(rect.left),
        top: Math.round(rect.top)
      }));
    }
  });

  const badgeEl = bar.querySelector("#suno-dl-badge");
  const submitBtn = bar.querySelector("#suno-dl-submit-btn");
  const clearBtn = bar.querySelector("#suno-dl-clear-btn");
  const autoCheck = bar.querySelector("#suno-dl-auto-check");

  // トースト表示関数
  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = "suno-dl-toast";
    toast.innerHTML = `
      <span style="font-size:16px;">${type === "error" ? "❌" : "✨"}</span>
      <span>${message}</span>
    `;
    document.body.appendChild(toast);
    setTimeout(() => {
      toast.style.transition = "opacity 0.4s";
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 400);
    }, 3500);
  }

  // 表示更新
  function updateBarUI() {
    const count = state.selectedUuids.size;
    badgeEl.textContent = count;
    submitBtn.textContent = `📥 選択した ${count} 曲をダウンロード`;
    if (count > 0) {
      bar.classList.remove("hidden");
    }
  }

  // 選択解除
  clearBtn.addEventListener("click", () => {
    state.selectedUuids.clear();
    updateBarUI();
    // Suno画面上のチェックボックスも連動解除
    document.querySelectorAll(".suno-dl-custom-check").forEach(cb => cb.checked = false);
    showToast("選択を解除しました", "info");
  });

  // ダウンロード実行
  submitBtn.addEventListener("click", async () => {
    if (state.selectedUuids.size === 0) {
      showToast("楽曲が選択されていません", "error");
      return;
    }

    const uuids = Array.from(state.selectedUuids);
    submitBtn.disabled = true;
    submitBtn.textContent = "送信中...";

    try {
      const resp = await fetch(`${API_BASE}/api/bulk_add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          uuids: uuids,
          auto_download: autoCheck.checked,
          format: state.format
        })
      });

      if (!resp.ok) {
        throw new Error(`サーバーエラー (HTTP ${resp.status})`);
      }

      const res = await resp.json();
      showToast(`🎉 ${res.count} 曲を Suno Downloader へ送信しました！${autoCheck.checked ? "（自動ダウンロード中）" : ""}`, "info");

      // 選択状態をリセット
      state.selectedUuids.clear();
      updateBarUI();
      document.querySelectorAll(".suno-dl-custom-check").forEach(cb => cb.checked = false);

    } catch (err) {
      console.error("[Suno Downloader] 送信エラー:", err);
      showToast(`送信失敗: Suno Downloaderアプリが起動しているか確認してください (http://127.0.0.1:8000)`, "error");
    } finally {
      submitBtn.disabled = false;
      updateBarUI();
    }
  });

  // 要素からUUIDを探索
  function findUuidInElement(el) {
    if (!el) return null;

    // 1. リンク先属性 (href) から抽出
    const link = el.closest("a") || el.querySelector("a[href*='/song/']");
    if (link && link.href) {
      const m = link.href.match(UUID_REGEX);
      if (m) return m[0].toLowerCase();
    }

    // 2. data属性から抽出
    const dataId = el.getAttribute("data-clip-id") || el.getAttribute("data-id") || el.getAttribute("data-clip");
    if (dataId && UUID_REGEX.test(dataId)) {
      return dataId.match(UUID_REGEX)[0].toLowerCase();
    }

    // 3. 親要素を探索
    let parent = el.parentElement;
    for (let i = 0; i < 5 && parent; i++) {
      const plink = parent.querySelector("a[href*='/song/']");
      if (plink && plink.href) {
        const m = plink.href.match(UUID_REGEX);
        if (m) return m[0].toLowerCase();
      }
      parent = parent.parentElement;
    }

    return null;
  }

  // --- Suno画面のDOM監視＆ボタン注入 ---
  function scanAndInject() {
    // 1. Suno公式のチェックボックス状態の検知
    const checkboxes = document.querySelectorAll('input[type="checkbox"], [role="checkbox"]');
    checkboxes.forEach(cb => {
      if (cb.dataset.sunoDlBound) return;
      cb.dataset.sunoDlBound = "true";

      cb.addEventListener("change", () => {
        setTimeout(() => {
          syncSelectedFromCheckboxes();
        }, 100);
      });
    });

    // 2. 各曲行・カードへの個別アクション追加
    const songLinks = document.querySelectorAll("a[href*='/song/']");
    songLinks.forEach(link => {
      const m = link.href.match(UUID_REGEX);
      if (!m) return;
      const uuid = m[0].toLowerCase();

      // カードまたは行コンテナを特定
      const row = link.closest("tr") || link.closest("[role='row']") || link.closest("li") || link.parentElement;
      if (!row || row.dataset.sunoDlInjected) return;
      row.dataset.sunoDlInjected = "true";

      // 個別ダウンロードボタンを挿入
      const btn = document.createElement("button");
      btn.className = "suno-dl-item-btn";
      btn.title = "この曲をSuno Downloaderで保存";
      btn.innerHTML = "📥";
      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        if (btn.disabled) return;

        btn.disabled = true;
        btn.textContent = "⏳";
        btn.style.opacity = "0.7";
        showToast("ダウンロードキューに追加しました（1曲ずつ順番に安全に処理されます）", "info");

        try {
          const resp = await fetch(`${API_BASE}/api/bulk_add`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              uuids: [uuid],
              auto_download: true,
              format: state.format
            })
          });
          if (resp.ok) {
            btn.textContent = "✅";
            btn.style.opacity = "1";
            showToast("ダウンロードが完了しました！", "info");
            setTimeout(() => {
              btn.textContent = "📥";
              btn.disabled = false;
            }, 3000);
          } else {
            throw new Error();
          }
        } catch {
          btn.textContent = "❌";
          btn.style.opacity = "1";
          showToast("Suno Downloaderアプリが起動していません", "error");
          setTimeout(() => {
            btn.textContent = "📥";
            btn.disabled = false;
          }, 3000);
        }
      });

      // 挿入場所を決定
      const actionArea = row.querySelector("button, [role='button']")?.parentElement || row;
      actionArea.appendChild(btn);
    });
  }

  // チェックボックスの状態を走査して同期
  function syncSelectedFromCheckboxes() {
    const checked = document.querySelectorAll('input[type="checkbox"]:checked, [role="checkbox"][aria-checked="true"]');
    checked.forEach(el => {
      const uuid = findUuidInElement(el);
      if (uuid) {
        state.selectedUuids.add(uuid);
      }
    });
    updateBarUI();
  }

  // MutationObserverで動的ローディングに対応
  const observer = new MutationObserver(() => {
    scanAndInject();
  });
  observer.observe(document.body, { childList: true, subtree: true });

  // 初回スキャン
  setTimeout(() => {
    scanAndInject();
  }, 1500);

  console.log("[Suno Downloader] ワークスペース＆楽曲連携アシスタントが起動しました。");
})();
