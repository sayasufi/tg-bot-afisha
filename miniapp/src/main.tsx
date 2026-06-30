// Entry gate. The map mini-app runs ONLY inside Telegram (it lives at app.okrestmap.ru). A plain browser
// is bounced to the landing (okrestmap.ru). The heavy map bundle is a dynamic import, so it's never even
// fetched outside Telegram — the browser just loads this tiny gate and redirects.
const tg = (window as { Telegram?: { WebApp?: { initData?: string; platform?: string } } }).Telegram?.WebApp;
const inTelegram = !!(tg && (tg.initData?.length || (tg.platform && tg.platform !== "unknown")));

const RETRY_KEY = "okrest_chunk_retry";

function recoveryUI(): void {
  // Last resort instead of an eternal WHITE screen: a tiny inline recovery card (no React — its chunk
  // is what failed to load). A deploy that deletes old hashed chunks an already-open shell points at is
  // the usual cause; the «Обновить» button clears the guard and reloads a fresh (no-cache) shell.
  document.body.innerHTML =
    '<div style="min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;' +
    'gap:18px;background:#0d0d0f;color:#f4f1ea;font-family:system-ui,-apple-system,sans-serif;padding:24px;text-align:center">' +
    '<div style="font-size:34px">📍</div>' +
    '<div style="font-size:16px;max-width:300px;line-height:1.4">Не удалось загрузить приложение — похоже, вышло обновление.</div>' +
    '<button id="okrest-reload" style="padding:12px 28px;border:0;background:#3300ff;color:#fff;font-size:15px;cursor:pointer">Обновить</button>' +
    "</div>";
  const btn = document.getElementById("okrest-reload");
  if (btn) {
    btn.onclick = () => {
      try { sessionStorage.removeItem(RETRY_KEY); } catch { /* ignore */ }
      window.location.reload();
    };
  }
}

function mountWithRetry(): void {
  import("./app/bootstrapApp")
    .then((m) => {
      try { sessionStorage.removeItem(RETRY_KEY); } catch { /* ignore */ }
      m.mountApp();
    })
    .catch(() => {
      let retried = false;
      try { retried = sessionStorage.getItem(RETRY_KEY) === "1"; } catch { /* ignore */ }
      if (!retried) {
        // ONE reload: the shell is now no-cache, so it comes back with the CURRENT chunk hashes.
        try { sessionStorage.setItem(RETRY_KEY, "1"); } catch { /* ignore */ }
        window.location.reload();
        return;
      }
      recoveryUI();
    });
}

if (inTelegram) {
  mountWithRetry();
} else {
  window.location.replace("https://okrestmap.ru/");
}
