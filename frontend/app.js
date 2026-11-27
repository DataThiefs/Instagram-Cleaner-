(() => {
  "use strict";

  const state = {
    auth: { authenticated: false, demo_mode: false, username: null },
    activeTab: "dm",
    threads: [],
    selectedThreads: new Set(),
    searchResults: [],
    selectedMessages: new Set(),
    stories: [],
    selectedStories: new Set(),
    storyMinAgeDays: 0,
    whitelist: [],
    jobPollTimer: null,
    lastJobStatus: "idle",
  };

  const $ = (id) => document.getElementById(id);

  // Register Service Worker for PWA
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------
  let toastTimer = null;
  function showToast(msg, duration = 3500) {
    const el = $("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), duration);
  }

  function escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("tr-TR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  }

  function getDelays() {
    const min = Math.max(0.5, parseFloat($("setting-min-delay")?.value || "2.5"));
    const max = Math.max(min, parseFloat($("setting-max-delay")?.value || "5.5"));
    return { min_delay: min, max_delay: max };
  }

  async function api(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || {};
      const err = new Error(detail.message || data.message || `HTTP ${res.status}`);
      err.code = detail.code || "API_ERROR";
      throw err;
    }
    return data;
  }

  // ------------------------------------------------------------------
  // Navigation & Auth UI
  // ------------------------------------------------------------------
  function setAuthenticatedUI(auth) {
    state.auth = auth;
    const isAuth = Boolean(auth.authenticated);
    $("view-auth").classList.toggle("hidden", isAuth);
    $("app-views").classList.toggle("hidden", !isAuth);
    $("desktop-nav").classList.toggle("hidden", !isAuth);
    $("mobile-nav").classList.toggle("hidden", !isAuth);
    $("user-badge").classList.toggle("hidden", !isAuth);

    if (isAuth) {
      $("user-handle").textContent = `@${auth.username || "instagram"}`;
      $("user-mode-pill").classList.toggle("hidden", !auth.demo_mode);
      switchTab(state.activeTab);
      loadThreads();
      loadWhitelist();
      loadNetworkInfo();
      pollJobStatus();
    }
  }

  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tab-view").forEach((el) => el.classList.add("hidden"));
    const target = $(`tab-${tab}`);
    if (target) target.classList.remove("hidden");

    document.querySelectorAll(".nav-btn, .mnav-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tab);
    });

    // Hide unrelated sticky action bars
    updateDmActionBar();
    updateSearchActionBar();
    updateStoryActionBar();

    if (tab === "stories" && state.stories.length === 0) {
      loadStories();
    }
  }

  // ------------------------------------------------------------------
  // Auth Handlers
  // ------------------------------------------------------------------
  document.querySelectorAll("[data-auth-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-auth-tab]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const mode = btn.dataset.authTab;
      $("form-session").classList.toggle("hidden", mode !== "session");
      $("form-creds").classList.toggle("hidden", mode !== "creds");
      $("panel-demo").classList.toggle("hidden", mode !== "demo");
    });
  });

  $("form-session").addEventListener("submit", async (e) => {
    e.preventDefault();
    const sessionid = $("input-sessionid").value.trim();
    if (!sessionid) return;
    const btn = e.target.querySelector("button[type='submit']");
    btn.disabled = true;
    btn.textContent = "Bağlanıyor...";
    try {
      const auth = await api("/api/auth/session", {
        method: "POST",
        body: JSON.stringify({ sessionid }),
      });
      showToast(`Hoş geldin @${auth.username}!`);
      setAuthenticatedUI(auth);
    } catch (err) {
      showToast(err.message, 5000);
    } finally {
      btn.disabled = false;
      btn.textContent = "Session ID ile Bağlan";
    }
  });

  $("form-creds").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = $("input-username").value.trim();
    const password = $("input-password").value;
    const verification_code = $("input-2fa").value.trim() || null;
    const btn = e.target.querySelector("button[type='submit']");
    btn.disabled = true;
    btn.textContent = "Giriş yapılıyor...";
    try {
      const auth = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password, verification_code }),
      });
      showToast(`Hoş geldin @${auth.username}!`);
      setAuthenticatedUI(auth);
    } catch (err) {
      if (err.code === "TWO_FACTOR_REQUIRED") {
        $("twofa-group").classList.remove("hidden");
        $("input-2fa").focus();
      }
      showToast(err.message, 5500);
    } finally {
      btn.disabled = false;
      btn.textContent = "Giriş Yap";
    }
  });

  $("btn-start-demo").addEventListener("click", async () => {
    try {
      const auth = await api("/api/auth/demo", { method: "POST" });
      showToast("Demo modu aktif! Tüm özellikleri güvenle deneyebilirsin.");
      setAuthenticatedUI(auth);
    } catch (err) {
      showToast(err.message);
    }
  });

  $("btn-logout").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    state.threads = [];
    state.stories = [];
    state.searchResults = [];
    state.selectedThreads.clear();
    state.selectedStories.clear();
    state.selectedMessages.clear();
    setAuthenticatedUI({ authenticated: false });
    showToast("Oturum kapatıldı.");
  });

  // Check URL hash/query for sessionid from browser extension
  function checkExtensionSessionParam() {
    const params = new URLSearchParams(window.location.search);
    const sid = params.get("sessionid");
    if (sid) {
      $("input-sessionid").value = sid;
      window.history.replaceState({}, document.title, "/");
      showToast("Eklentiden sessionid alındı! Bağlan butonuna tıklayabilirsin.");
    }
  }

  // ------------------------------------------------------------------
  // DM Threads
  // ------------------------------------------------------------------
  async function loadThreads() {
    const list = $("dm-list");
    list.innerHTML = `<div class="empty-state">DM sohbetleri yükleniyor...</div>`;
    try {
      state.threads = await api("/api/dm/threads?amount=60");
      state.selectedThreads.clear();
      renderThreads();
    } catch (err) {
      list.innerHTML = `<div class="empty-state">DM sohbetleri yüklenemedi: ${escapeHtml(err.message)}</div>`;
    }
  }

  function getFilteredThreads() {
    const q = ($("dm-filter-input").value || "").trim().toLowerCase();
    if (!q) return state.threads;
    return state.threads.filter((t) => {
      const blob = `${t.title} ${t.usernames.join(" ")} ${t.last_message}`.toLowerCase();
      return blob.includes(q);
    });
  }

  function renderThreads() {
    const list = $("dm-list");
    const items = getFilteredThreads();
    if (!items.length) {
      list.innerHTML = `<div class="empty-state">Gösterilecek DM sohbeti bulunamadı.</div>`;
      updateDmActionBar();
      return;
    }

    list.innerHTML = items
      .map((t) => {
        const checked = state.selectedThreads.has(t.thread_id);
        const initial = (t.title || "?").charAt(0).toUpperCase();
        const primaryUser = t.usernames[0] || "";
        return `
          <div class="list-card ${checked ? "selected" : ""}" data-tid="${escapeHtml(t.thread_id)}">
            <input type="checkbox" class="dm-check" data-tid="${escapeHtml(t.thread_id)}" ${checked ? "checked" : ""} />
            <div class="avatar">${escapeHtml(initial)}</div>
            <div class="item-body">
              <div class="item-title-row">
                <span class="item-title">${escapeHtml(t.title)}</span>
                ${t.is_group ? `<span class="pill">Grup</span>` : ""}
                ${t.is_whitelisted ? `<span class="pill pill-safe">Korunan</span>` : ""}
                <span class="muted" style="margin-left:auto;font-size:0.78rem;">${formatDate(t.last_activity)}</span>
              </div>
              <div class="item-sub">${escapeHtml(t.last_message || "Mesaj önizlemesi yok")}</div>
            </div>
            ${
              primaryUser
                ? `<button class="shield-btn ${t.is_whitelisted ? "protected" : ""}" data-wl-user="${escapeHtml(primaryUser)}" data-wl-active="${t.is_whitelisted ? "1" : "0"}" title="Koruma Listesine Ekle/Çıkar">
                    ${t.is_whitelisted ? "🛡️ Korunan" : "🛡️ Koru"}
                   </button>`
                : ""
            }
          </div>
        `;
      })
      .join("");

    list.querySelectorAll(".dm-check").forEach((cb) => {
      cb.addEventListener("change", () => {
        const tid = cb.dataset.tid;
        if (cb.checked) state.selectedThreads.add(tid);
        else state.selectedThreads.delete(tid);
        cb.closest(".list-card").classList.toggle("selected", cb.checked);
        updateDmActionBar();
      });
    });

    list.querySelectorAll(".shield-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const user = btn.dataset.wlUser;
        const active = btn.dataset.wlActive === "1";
        if (active) {
          await api(`/api/whitelist/${encodeURIComponent(user)}`, { method: "DELETE" });
          showToast(`@${user} koruma listesinden çıkarıldı.`);
        } else {
          await api("/api/whitelist", { method: "POST", body: JSON.stringify({ username: user }) });
          showToast(`@${user} koruma listesine eklendi.`);
        }
        await loadWhitelist();
        await loadThreads();
      });
    });

    updateDmActionBar();
  }

  function updateDmActionBar() {
    const bar = $("dm-action-bar");
    const count = state.selectedThreads.size;
    const show = state.activeTab === "dm" && count > 0;
    bar.classList.toggle("hidden", !show);
    $("dm-selected-count").textContent = `${count} sohbet seçildi`;
  }

  $("dm-filter-input").addEventListener("input", renderThreads);
  $("btn-refresh-dm").addEventListener("click", loadThreads);

  $("btn-dm-select-all").addEventListener("click", () => {
    getFilteredThreads().forEach((t) => state.selectedThreads.add(t.thread_id));
    renderThreads();
  });

  $("btn-dm-select-unprotected").addEventListener("click", () => {
    state.selectedThreads.clear();
    getFilteredThreads()
      .filter((t) => !t.is_whitelisted)
      .forEach((t) => state.selectedThreads.add(t.thread_id));
    renderThreads();
  });

  $("btn-dm-clear-sel").addEventListener("click", () => {
    state.selectedThreads.clear();
    renderThreads();
  });

  $("btn-dm-delete").addEventListener("click", async () => {
    const ids = Array.from(state.selectedThreads);
    if (!ids.length) return;
    const dryRun = $("dm-dry-run").checked;
    const unsendFirst = $("dm-unsend-first").checked;
    if (!dryRun && !confirm(`${ids.length} DM sohbeti silinecek. Devam etmek istiyor musun?`)) {
      return;
    }
    try {
      const delays = getDelays();
      await api("/api/dm/delete-threads", {
        method: "POST",
        body: JSON.stringify({
          thread_ids: ids,
          unsend_my_messages_first: unsendFirst,
          dry_run: dryRun,
          ...delays,
        }),
      });
      state.selectedThreads.clear();
      renderThreads();
      startJobPolling();
    } catch (err) {
      showToast(err.message, 4500);
    }
  });

  // ------------------------------------------------------------------
  // Keyword Search & Unsend
  // ------------------------------------------------------------------
  $("form-dm-search").addEventListener("submit", async (e) => {
    e.preventDefault();
    const keyword = $("search-keyword-input").value.trim();
    if (!keyword) return;
    const list = $("search-results-list");
    list.innerHTML = `<div class="empty-state">"${escapeHtml(keyword)}" kelimesi DM mesajlarında taranıyor...</div>`;
    $("search-results-header").classList.add("hidden");
    state.selectedMessages.clear();
    updateSearchActionBar();

    try {
      const results = await api("/api/dm/search", {
        method: "POST",
        body: JSON.stringify({
          keyword,
          only_mine: $("search-only-mine").checked,
          case_sensitive: $("search-case-sensitive").checked,
          limit_per_thread: 60,
        }),
      });
      state.searchResults = results;
      renderSearchResults(keyword);
    } catch (err) {
      list.innerHTML = `<div class="empty-state">Arama hatası: ${escapeHtml(err.message)}</div>`;
    }
  });

  function highlightKeyword(text, keyword) {
    const safeText = escapeHtml(text);
    const safeKey = escapeHtml(keyword).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    if (!safeKey) return safeText;
    const re = new RegExp(`(${safeKey})`, "gi");
    return safeText.replace(re, `<span class="highlight">$1</span>`);
  }

  function renderSearchResults(keyword = "") {
    const list = $("search-results-list");
    const hdr = $("search-results-header");
    if (!state.searchResults.length) {
      hdr.classList.add("hidden");
      list.innerHTML = `<div class="empty-state">Bu kelimeyle eşleşen mesaj bulunamadı.</div>`;
      updateSearchActionBar();
      return;
    }

    hdr.classList.remove("hidden");
    $("search-results-count").textContent = `${state.searchResults.length} eşleşen mesaj bulundu`;

    list.innerHTML = state.searchResults
      .map((m) => {
        const key = `${m.thread_id}::${m.message_id}`;
        const checked = state.selectedMessages.has(key);
        return `
          <div class="list-card ${checked ? "selected" : ""}">
            <input type="checkbox" class="msg-check" data-key="${escapeHtml(key)}" ${checked ? "checked" : ""} ${!m.is_mine ? "disabled" : ""} />
            <div class="item-body">
              <div class="item-title-row">
                <span class="item-title">${escapeHtml(m.thread_title)}</span>
                <span class="pill ${m.is_mine ? "pill-safe" : ""}">${m.is_mine ? "Benim Mesajım" : "Karşı Taraf"}</span>
                <span class="muted" style="margin-left:auto;font-size:0.78rem;">${formatDate(m.timestamp)}</span>
              </div>
              <div class="item-sub wrap">${highlightKeyword(m.text, keyword)}</div>
            </div>
          </div>
        `;
      })
      .join("");

    list.querySelectorAll(".msg-check").forEach((cb) => {
      cb.addEventListener("change", () => {
        const key = cb.dataset.key;
        if (cb.checked) state.selectedMessages.add(key);
        else state.selectedMessages.delete(key);
        cb.closest(".list-card").classList.toggle("selected", cb.checked);
        updateSearchActionBar();
      });
    });
    updateSearchActionBar();
  }

  function updateSearchActionBar() {
    const bar = $("search-action-bar");
    const count = state.selectedMessages.size;
    const show = state.activeTab === "search" && count > 0;
    bar.classList.toggle("hidden", !show);
    $("search-selected-count").textContent = `${count} mesaj seçildi`;
  }

  $("btn-search-select-all").addEventListener("click", () => {
    state.searchResults
      .filter((m) => m.is_mine)
      .forEach((m) => state.selectedMessages.add(`${m.thread_id}::${m.message_id}`));
    renderSearchResults($("search-keyword-input").value.trim());
  });

  $("btn-search-clear-sel").addEventListener("click", () => {
    state.selectedMessages.clear();
    renderSearchResults($("search-keyword-input").value.trim());
  });

  $("btn-search-unsend").addEventListener("click", async () => {
    const selectedKeys = Array.from(state.selectedMessages);
    if (!selectedKeys.length) return;
    const dryRun = $("search-dry-run").checked;
    if (!dryRun && !confirm(`${selectedKeys.length} mesaj geri alınacak (Unsend). Devam edilsin mi?`)) {
      return;
    }

    const map = new Map(state.searchResults.map((m) => [`${m.thread_id}::${m.message_id}`, m]));
    const items = selectedKeys
      .map((k) => map.get(k))
      .filter(Boolean)
      .map((m) => ({
        thread_id: m.thread_id,
        message_id: m.message_id,
        preview: m.text.slice(0, 60),
      }));

    try {
      const delays = getDelays();
      await api("/api/dm/unsend", {
        method: "POST",
        body: JSON.stringify({ items, dry_run: dryRun, ...delays }),
      });
      state.selectedMessages.clear();
      updateSearchActionBar();
      startJobPolling();
    } catch (err) {
      showToast(err.message, 4500);
    }
  });

  // ------------------------------------------------------------------
  // Story Archive
  // ------------------------------------------------------------------
  async function loadStories() {
    const grid = $("stories-grid");
    grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">Arşiv hikayeler yükleniyor...</div>`;
    try {
      state.stories = await api("/api/stories/archive?limit=150");
      state.selectedStories.clear();
      renderStories();
    } catch (err) {
      grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">Arşiv yüklenemedi: ${escapeHtml(err.message)}</div>`;
    }
  }

  function getFilteredStories() {
    const nowSec = Math.floor(Date.now() / 1000);
    const customDate = $("story-before-date").value;
    const customCutoff = customDate ? Math.floor(new Date(customDate + "T23:59:59Z").getTime() / 1000) : null;

    return state.stories.filter((s) => {
      if (state.storyMinAgeDays > 0) {
        const cutoff = nowSec - state.storyMinAgeDays * 86400;
        if (s.taken_at_ts > cutoff) return false;
      }
      if (customCutoff !== null && s.taken_at_ts > customCutoff) {
        return false;
      }
      return true;
    });
  }

  function renderStories() {
    const grid = $("stories-grid");
    const items = getFilteredStories();
    if (!items.length) {
      grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;">Filtreye uygun arşiv hikaye bulunamadı.</div>`;
      updateStoryActionBar();
      return;
    }

    grid.innerHTML = items
      .map((s) => {
        const selected = state.selectedStories.has(s.media_id);
        return `
          <div class="story-card ${selected ? "selected" : ""}" data-mid="${escapeHtml(s.media_id)}">
            ${s.thumbnail_url ? `<img src="${escapeHtml(s.thumbnail_url)}" alt="Story" loading="lazy" />` : ""}
            <div class="story-overlay">
              <div class="story-top">
                <span class="pill">${escapeHtml(s.media_type)}</span>
                <span class="story-check">${selected ? "✓" : ""}</span>
              </div>
              <div class="story-date">${formatDate(s.taken_at)}</div>
            </div>
          </div>
        `;
      })
      .join("");

    grid.querySelectorAll(".story-card").forEach((card) => {
      card.addEventListener("click", () => {
        const mid = card.dataset.mid;
        if (state.selectedStories.has(mid)) state.selectedStories.delete(mid);
        else state.selectedStories.add(mid);
        renderStories();
      });
    });

    updateStoryActionBar();
  }

  function updateStoryActionBar() {
    const bar = $("story-action-bar");
    const count = state.selectedStories.size;
    const show = state.activeTab === "stories" && count > 0;
    bar.classList.toggle("hidden", !show);
    $("story-selected-count").textContent = `${count} hikaye seçildi`;
  }

  $("story-age-chips").querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      $("story-age-chips").querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
      chip.classList.add("active");
      state.storyMinAgeDays = parseInt(chip.dataset.days || "0", 10);
      renderStories();
    });
  });

  $("story-before-date").addEventListener("change", renderStories);
  $("btn-refresh-stories").addEventListener("click", loadStories);

  $("btn-story-select-all").addEventListener("click", () => {
    getFilteredStories().forEach((s) => state.selectedStories.add(s.media_id));
    renderStories();
  });

  $("btn-story-clear-sel").addEventListener("click", () => {
    state.selectedStories.clear();
    renderStories();
  });

  $("btn-story-delete").addEventListener("click", async () => {
    const ids = Array.from(state.selectedStories);
    if (!ids.length) return;
    const dryRun = $("story-dry-run").checked;
    if (!dryRun && !confirm(`${ids.length} arşivlenmiş hikaye kalıcı olarak silinecek. Devam edilsin mi?`)) {
      return;
    }
    const map = new Map(state.stories.map((s) => [s.media_id, s]));
    const items = ids
      .map((id) => map.get(id))
      .filter(Boolean)
      .map((s) => ({ media_id: s.media_id, media_type: s.media_type, taken_at: s.taken_at }));

    try {
      const delays = getDelays();
      await api("/api/stories/delete", {
        method: "POST",
        body: JSON.stringify({ items, dry_run: dryRun, ...delays }),
      });
      state.selectedStories.clear();
      renderStories();
      startJobPolling();
    } catch (err) {
      showToast(err.message, 4500);
    }
  });

  // ------------------------------------------------------------------
  // All Clean
  // ------------------------------------------------------------------
  $("btn-start-allclean").addEventListener("click", async () => {
    const payload = {
      delete_dm_threads: $("ac-dm-threads").checked,
      unsend_my_messages: $("ac-unsend-mine").checked,
      delete_archived_stories: $("ac-stories").checked,
      respect_whitelist: $("ac-respect-whitelist").checked,
      dry_run: $("ac-dry-run").checked,
      ...getDelays(),
    };

    if (!payload.delete_dm_threads && !payload.delete_archived_stories) {
      showToast("En az bir temizlik seçeneği seçmelisin.");
      return;
    }

    if (!payload.dry_run) {
      const answer = prompt(
        "ALL CLEAN işlemi GERÇEK silme yapacak!\nOnaylamak için büyük harfle TEMIZLE yaz:"
      );
      if (answer !== "TEMIZLE") {
        showToast("All Clean iptal edildi.");
        return;
      }
    }

    try {
      await api("/api/clean/all", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      startJobPolling();
    } catch (err) {
      showToast(err.message, 4500);
    }
  });

  // ------------------------------------------------------------------
  // Whitelist & Network Info
  // ------------------------------------------------------------------
  async function loadWhitelist() {
    try {
      const data = await api("/api/whitelist");
      state.whitelist = data.usernames || [];
      renderWhitelist();
    } catch (_) {}
  }

  function renderWhitelist() {
    const box = $("whitelist-chips");
    if (!state.whitelist.length) {
      box.innerHTML = `<span class="muted">Henüz korunan hesap yok.</span>`;
      return;
    }
    box.innerHTML = state.whitelist
      .map(
        (u) => `
        <span class="chip">
          🛡️ @${escapeHtml(u)}
          <button class="chip-remove" data-rm-wl="${escapeHtml(u)}" title="Kaldır">×</button>
        </span>
      `
      )
      .join("");

    box.querySelectorAll("[data-rm-wl]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const u = btn.dataset.rmWl;
        await api(`/api/whitelist/${encodeURIComponent(u)}`, { method: "DELETE" });
        await loadWhitelist();
        await loadThreads();
        showToast(`@${u} koruma listesinden çıkarıldı.`);
      });
    });
  }

  $("form-whitelist").addEventListener("submit", async (e) => {
    e.preventDefault();
    const u = $("whitelist-input").value.trim();
    if (!u) return;
    await api("/api/whitelist", { method: "POST", body: JSON.stringify({ username: u }) });
    $("whitelist-input").value = "";
    await loadWhitelist();
    await loadThreads();
    showToast(`@${u.replace(/^@/, "")} koruma listesine eklendi.`);
  });

  async function loadNetworkInfo() {
    try {
      const net = await api("/api/network");
      $("mobile-url-input").value = net.mobile_url;
    } catch (_) {
      $("mobile-url-input").value = window.location.origin;
    }
  }

  $("btn-copy-mobile-url").addEventListener("click", async () => {
    const val = $("mobile-url-input").value;
    try {
      await navigator.clipboard.writeText(val);
      showToast("Mobil bağlantı adresi kopyalandı!");
    } catch (_) {
      $("mobile-url-input").select();
      document.execCommand("copy");
      showToast("Adres kopyalandı!");
    }
  });

  // ------------------------------------------------------------------
  // Job Polling & Controls
  // ------------------------------------------------------------------
  function startJobPolling() {
    clearInterval(state.jobPollTimer);
    pollJobStatus();
    state.jobPollTimer = setInterval(pollJobStatus, 900);
  }

  async function pollJobStatus() {
    try {
      const job = await api("/api/jobs/status");
      renderJobPanel(job);
      const active = job.status === "running" || job.status === "paused";
      if (!active && state.jobPollTimer) {
        clearInterval(state.jobPollTimer);
        state.jobPollTimer = null;
        if (state.lastJobStatus === "running" || state.lastJobStatus === "paused") {
          loadThreads();
          if (state.stories.length > 0 || job.job_type === "all_clean" || job.job_type === "delete_stories") {
            loadStories();
          }
        }
      }
      state.lastJobStatus = job.status;
    } catch (_) {}
  }

  function renderJobPanel(job) {
    const panel = $("job-panel");
    if (!job || job.status === "idle") {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");

    const titles = {
      delete_threads: "DM Sohbet Temizliği",
      unsend_messages: "Mesaj Geri Alma (Unsend)",
      delete_stories: "Arşiv Hikaye Temizliği",
      all_clean: "All Clean (Tam Temizlik)",
    };
    const statusMap = {
      running: ["Çalışıyor", "pill-running"],
      paused: ["Duraklatıldı", "pill-demo"],
      completed: ["Tamamlandı", "pill-safe"],
      stopped: ["Durduruldu", "pill-demo"],
      error: ["Hata", "pill-running"],
    };

    const [stLabel, stClass] = statusMap[job.status] || [job.status, ""];
    const pill = $("job-status-pill");
    pill.textContent = job.dry_run ? `${stLabel} (Önizleme)` : stLabel;
    pill.className = `pill ${stClass}`;

    $("job-title").textContent = titles[job.job_type] || "Temizlik Görevi";
    const pct = job.total > 0 ? Math.min(100, Math.round((job.processed / job.total) * 100)) : 0;
    $("job-progress-bar").style.width = `${pct}%`;
    $("job-action-text").textContent = job.current_action || "";
    $("job-counts").textContent = `${job.processed}/${job.total} • ✓${job.succeeded} • ✕${job.failed}${job.skipped ? ` • 🛡️${job.skipped}` : ""}`;

    const isRunning = job.status === "running";
    const isPaused = job.status === "paused";
    const isDone = !isRunning && !isPaused;
    $("btn-job-pause").classList.toggle("hidden", !isRunning);
    $("btn-job-resume").classList.toggle("hidden", !isPaused);
    $("btn-job-stop").classList.toggle("hidden", isDone);
    $("btn-job-close").classList.toggle("hidden", !isDone);

    const logBox = $("job-logs");
    logBox.innerHTML = (job.logs || [])
      .map(
        (l) =>
          `<div class="log-${escapeHtml(l.level)}">[${escapeHtml(l.time)}] ${escapeHtml(l.message)}</div>`
      )
      .join("");
    logBox.scrollTop = logBox.scrollHeight;
  }

  $("btn-job-pause").addEventListener("click", async () => {
    const job = await api("/api/jobs/pause", { method: "POST" });
    renderJobPanel(job);
  });

  $("btn-job-resume").addEventListener("click", async () => {
    const job = await api("/api/jobs/resume", { method: "POST" });
    renderJobPanel(job);
    startJobPolling();
  });

  $("btn-job-stop").addEventListener("click", async () => {
    const job = await api("/api/jobs/stop", { method: "POST" });
    renderJobPanel(job);
  });

  $("btn-job-close").addEventListener("click", () => {
    $("job-panel").classList.add("hidden");
  });

  // Tab bindings
  document.querySelectorAll(".nav-btn, .mnav-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  // Init
  async function init() {
    checkExtensionSessionParam();
    try {
      const auth = await api("/api/auth/status");
      setAuthenticatedUI(auth);
    } catch (_) {
      setAuthenticatedUI({ authenticated: false });
    }
  }

  init();
})();
