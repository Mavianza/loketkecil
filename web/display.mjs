const $ = (id) => document.getElementById(id),
  el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
let refreshing = false,
  lastSuccess = 0,
  lastRevision = -1;
function render(data) {
  const session = data.session;
  $("display-title").textContent = session?.title || "Belum ada sesi layanan.";
  $("display-day").textContent = session?.day || "Menunggu sesi";
  $("display-status").textContent = !session
    ? "Silakan menunggu petugas membuka sesi."
    : session.closed_at
      ? "Sesi telah ditutup. Terima kasih sudah menunggu dengan tertib."
      : session.synthetic
        ? "Data contoh sintetis · hanya untuk mencoba aplikasi."
        : "Perhatikan nomor dan nama loket yang muncul.";
  $("display-counters").replaceChildren();
  for (const counter of data.counters) {
    const node = el(
      "section",
      "display-counter " + (counter.code ? "active" : ""),
    );
    node.append(
      el("h2", "", counter.label),
      el("strong", "", counter.code || "—"),
      el(
        "p",
        "",
        counter.code ? "Silakan menuju loket" : "Menunggu panggilan berikutnya",
      ),
    );
    $("display-counters").append(node);
  }
  $("display-next-numbers").replaceChildren();
  for (const code of data.next)
    $("display-next-numbers").append(el("span", "", code));
  if (!data.next.length)
    $("display-next-numbers").textContent = "Belum ada nomor menunggu.";
  $("display-wait-count").textContent = `${data.counts.waiting} nomor menunggu`;
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch("/api/display", {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Layar belum tersambung");
    const data = await response.json();
    lastSuccess = Date.now();
    $("display-alert").hidden = true;
    if (data.revision !== lastRevision) {
      render(data);
      lastRevision = data.revision;
    }
    $("display-updated").textContent =
      "Data diperbarui " +
      new Intl.DateTimeFormat("id-ID", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(new Date(data.server_time));
  } catch {
    $("display-alert").hidden = false;
  } finally {
    refreshing = false;
  }
}
setInterval(() => {
  $("display-clock").textContent = new Intl.DateTimeFormat("id-ID", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date());
  if (lastSuccess && Date.now() - lastSuccess > 10000)
    $("display-alert").hidden = false;
}, 1000);
refresh();
setInterval(refresh, 2000);
