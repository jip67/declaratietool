// Registreer de service worker, zodat de tool als app op het beginscherm kan.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  });
}

// Teller op het app-icoon: het aantal taken dat op jou wacht.
// Werkt op iPhone/iPad (app op beginscherm, meldingen toegestaan) en op Windows/macOS;
// Android toont geen teller zonder pushmeldingen.
function setBadge(count) {
  if (!("setAppBadge" in navigator)) return;
  (count > 0 ? navigator.setAppBadge(count) : navigator.clearAppBadge()).catch(() => {});
}

const badge = document.body.dataset.badge;
if (badge !== undefined) setBadge(parseInt(badge, 10) || 0);

// Komt de app terug op de voorgrond zonder te herladen, haal dan het actuele aantal op.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || document.body.dataset.badge === undefined) return;
  if (!document.body.classList.contains("has-sidebar")) return;
  fetch("/badge", { headers: { Accept: "application/json" } })
    .then((r) => (r.ok && (r.headers.get("content-type") || "").startsWith("application/json") ? r.json() : null))
    .then((data) => { if (data) setBadge(data.count); })
    .catch(() => {});
});

// iPhone/iPad tonen de teller alleen als meldingen zijn toegestaan; daarvoor een knop op Mijn account.
const allow = document.getElementById("badge-allow");
const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
if (allow && standalone && "setAppBadge" in navigator && "Notification" in window && Notification.permission === "default") {
  allow.hidden = false;
  allow.querySelector("button").addEventListener("click", () => {
    Notification.requestPermission().then(() => {
      allow.hidden = true;
      setBadge(parseInt(document.body.dataset.badge, 10) || 0);
    });
  });
}
