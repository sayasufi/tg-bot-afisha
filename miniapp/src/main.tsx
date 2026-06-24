// Entry gate. The map mini-app runs ONLY inside Telegram (it lives at app.okrestmap.ru). A plain browser
// is bounced to the landing (okrestmap.ru). The heavy map bundle is a dynamic import, so it's never even
// fetched outside Telegram — the browser just loads this tiny gate and redirects.
const tg = (window as { Telegram?: { WebApp?: { initData?: string; platform?: string } } }).Telegram?.WebApp;
const inTelegram = !!(tg && (tg.initData?.length || (tg.platform && tg.platform !== "unknown")));

if (inTelegram) {
  void import("./app/bootstrapApp").then((m) => m.mountApp());
} else {
  window.location.replace("https://okrestmap.ru/");
}
