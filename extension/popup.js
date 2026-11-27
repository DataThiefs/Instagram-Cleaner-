const statusEl = document.getElementById("status");
const urlInput = document.getElementById("server-url");

function setStatus(msg, isErr = false) {
  statusEl.textContent = msg;
  statusEl.className = isErr ? "err" : "";
}

async function getInstagramSessionId() {
  const cookie = await chrome.cookies.get({
    url: "https://www.instagram.com",
    name: "sessionid",
  });
  if (!cookie || !cookie.value) {
    throw new Error("Instagram oturumu bulunamadı. Önce instagram.com'a giriş yapın.");
  }
  return cookie.value;
}

document.getElementById("btn-copy").addEventListener("click", async () => {
  try {
    const sid = await getInstagramSessionId();
    await navigator.clipboard.writeText(sid);
    setStatus("sessionid panoya kopyalandı!");
  } catch (err) {
    setStatus(err.message, true);
  }
});

document.getElementById("btn-open").addEventListener("click", async () => {
  try {
    const sid = await getInstagramSessionId();
    const base = (urlInput.value || "http://127.0.0.1:8000").replace(/\/+$/, "");
    const targetUrl = `${base}/?sessionid=${encodeURIComponent(sid)}`;
    await chrome.tabs.create({ url: targetUrl });
    setStatus("Panel açıldı!");
  } catch (err) {
    setStatus(err.message, true);
  }
});
