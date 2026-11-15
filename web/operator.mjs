import { Outbox } from "./outbox.mjs";
const $ = (id) => document.getElementById(id),
  names = {
    waiting: "Menunggu",
    serving: "Dilayani",
    done: "Selesai",
    skipped: "Dilewatkan",
    cancelled: "Dibatalkan",
  };
const number = (n) => new Intl.NumberFormat("id-ID").format(n),
  el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
let state = null,
  selected = null,
  busy = false,
  pending = null,
  outbox = null,
  outboxBroken = false,
  lastSuccess = 0,
  confirmPayload = null,
  toastTimer,
  refreshing = false,
  refreshAgain = false;
function toast(text, error = false) {
  clearTimeout(toastTimer);
  $("toast").textContent = text;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  toastTimer = setTimeout(() => {
    $("toast").hidden = true;
  }, 6500);
}
function closeDialogs() {
  document.querySelectorAll("dialog[open]").forEach((dialog) => dialog.close());
}
document
  .querySelectorAll("[data-close]")
  .forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
function live() {
  return Boolean(
    state?.selected &&
      !state.selected.closed_at &&
      state.selected.id === state.active_id,
  );
}
function locked() {
  return (
    busy ||
    Boolean(pending) ||
    outboxBroken ||
    !state ||
    Date.now() - lastSuccess > 12000
  );
}
function renderLocks() {
  for (const button of document.querySelectorAll("[data-mutation]"))
    button.disabled =
      locked() ||
      !live() ||
      (button.dataset.action === "call" && state?.counts.waiting === 0);
  $("issue-button").disabled = locked() || !live();
  $("alias").disabled = locked() || !live();
  $("new-session").disabled = locked() || Boolean(state?.active_id);
  $("start-session").disabled = locked();
  $("load-demo").disabled = locked();
  $("close-session").disabled = locked() || !live();
  $("retry-pending").disabled = busy || !pending || outboxBroken;
  $("pending-banner").hidden = !pending && !outboxBroken;
  if (outboxBroken)
    $("pending-text").textContent =
      "Pengingat permintaan tidak bisa diakses. Status server tetap bisa dilihat. Periksa izin penyimpanan browser dan cadangkan data sebelum membersihkannya.";
}
function showError(message) {
  $("error-text").textContent = message;
  $("error-banner").hidden = false;
  $("connection").textContent = "Koneksi perlu diperiksa";
  $("connection").classList.add("offline");
  renderLocks();
}
function time(iso) {
  return new Intl.DateTimeFormat("id-ID", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}
function render() {
  const session = state.selected;
  $("welcome").hidden = Boolean(session);
  $("workspace").hidden = !session;
  $("synthetic-note").hidden = !session?.synthetic;
  $("archive-note").hidden = !session?.closed_at;
  $("session-title").textContent =
    session?.title || "Selamat datang di LoketKecil.";
  $("session-subtitle").textContent = session
    ? `${session.day} · ${session.closed_at ? "Sesi ditutup" : "Sesi sedang berjalan"} · ${state.counters.length} loket dalam satu antrean`
    : "Mulai satu sesi layanan, lalu bagikan nomor antrean.";
  $("close-session").hidden = !session || Boolean(session.closed_at);
  $("new-session").hidden = Boolean(state.active_id);
  $("session-select").replaceChildren();
  if (!state.sessions.length)
    $("session-select").add(new Option("Belum ada sesi", ""));
  for (const s of state.sessions)
    $("session-select").add(
      new Option(
        `${s.day} · ${s.title}${s.closed_at ? " (arsip)" : ""}`,
        String(s.id),
      ),
    );
  $("session-select").value = session ? String(session.id) : "";
  $("session-select").disabled = !state.sessions.length || busy;
  if (session) {
    $("count-waiting").textContent = number(state.counts.waiting);
    $("count-serving").textContent = number(state.counts.serving);
    $("count-done").textContent = number(state.counts.done);
    $("count-other").textContent = number(
      state.counts.skipped + state.counts.cancelled,
    );
    $("open-counter-count").textContent = `dari ${state.counters.length} loket`;
    $("csv-link").href = "/api/report.csv?session_id=" + session.id;
    $("counters").replaceChildren();
    for (const counter of state.counters) {
      const card = el(
          "article",
          "counter " + (counter.ticket ? "occupied" : ""),
        ),
        top = el("div", "counter-top");
      top.append(
        el("h3", "", counter.label),
        el(
          "span",
          "counter-status",
          counter.ticket ? "Melayani" : "Siap melayani",
        ),
      );
      card.append(top);
      card.append(
        el("strong", "counter-number", counter.ticket?.code || "—"),
        el(
          "p",
          "counter-alias",
          counter.ticket
            ? counter.ticket.alias || "Tanpa alias"
            : "Panggil nomor berikutnya dari antrean.",
        ),
      );
      const actions = el("div", "counter-actions");
      if (counter.ticket) {
        actions.append(
          actionButton(
            "Selesai",
            {
              action: "finish",
              session_id: session.id,
              ticket_id: counter.ticket.id,
              expected_version: counter.ticket.version,
            },
            "button primary",
            "Selesaikan " + counter.ticket.code + " di " + counter.label,
          ),
          actionButton(
            "Lewati",
            {
              action: "skip",
              session_id: session.id,
              ticket_id: counter.ticket.id,
              expected_version: counter.ticket.version,
            },
            "button outline",
            "Lewati " + counter.ticket.code + " di " + counter.label,
            true,
          ),
        );
      } else
        actions.append(
          actionButton(
            "Panggil berikutnya",
            {
              action: "call",
              session_id: session.id,
              counter_id: counter.id,
              expected_version: counter.version,
            },
            "button primary full",
            "Panggil berikutnya di " + counter.label,
          ),
        );
      card.append(actions);
      $("counters").append(card);
    }
    renderTickets();
    $("events").replaceChildren();
    for (const event of state.events) {
      const li = el("li"),
        dot = el("i");
      li.append(
        dot,
        el("p", "", event.message),
        el("time", "", time(event.created_at)),
      );
      $("events").append(li);
    }
    $("ticket-total").textContent = number(state.tickets.length) + " nomor";
  }
  $("last-update").textContent = "Diperbarui " + time(state.server_time);
  renderLocks();
}
function actionButton(label, payload, cls, accessible, confirm = false) {
  const button = el("button", cls, label);
  button.type = "button";
  button.dataset.mutation = "true";
  button.dataset.action = payload.action;
  button.setAttribute("aria-label", accessible);
  button.addEventListener("click", () => {
    if (!confirm) return mutate(payload);
    if (payload.action === "cancel")
      ask(
        payload,
        "Batalkan nomor ini?",
        "Nomor tetap tercatat sebagai dibatalkan dan tidak akan dipakai ulang.",
        "Ya, batalkan",
      );
    else
      ask(
        payload,
        "Lewati nomor ini?",
        "Nomor tetap tercatat. Jika pengunjung kembali, masukkan ulang di akhir antrean.",
        "Ya, lewati",
      );
  });
  return button;
}
function renderTickets() {
  const query = $("ticket-search").value.trim().toLocaleLowerCase("id-ID"),
    status = $("status-filter").value;
  const rows = state.tickets.filter(
      (t) =>
        (status === "all" || t.status === status) &&
        [t.code, t.alias].join(" ").toLocaleLowerCase("id-ID").includes(query),
    ),
    labels = new Map(state.counters.map((c) => [c.id, c.label]));
  $("tickets").replaceChildren();
  for (const ticket of rows) {
    const row = el("tr");
    row.append(
      el("td", "ticket-code", ticket.code),
      el("td", "alias-cell", ticket.alias || "—"),
    );
    const statusCell = el("td");
    statusCell.append(
      el("span", "status " + ticket.status, names[ticket.status]),
    );
    row.append(statusCell, el("td", "", labels.get(ticket.counter_id) || "—"));
    const cell = el("td");
    if (ticket.status === "waiting")
      cell.append(
        actionButton(
          "Batalkan",
          {
            action: "cancel",
            session_id: state.selected.id,
            ticket_id: ticket.id,
            expected_version: ticket.version,
          },
          "text-link danger",
          "Batalkan " + ticket.code,
          true,
        ),
      );
    else if (ticket.status === "skipped")
      cell.append(
        actionButton(
          "Masuk ulang",
          {
            action: "requeue",
            session_id: state.selected.id,
            ticket_id: ticket.id,
            expected_version: ticket.version,
          },
          "text-link",
          "Masukkan ulang " + ticket.code,
        ),
      );
    else cell.textContent = "—";
    row.append(cell);
    $("tickets").append(row);
  }
  $("ticket-empty").hidden = Boolean(rows.length);
  $("table-count").textContent =
    `${rows.length} dari ${state.tickets.length} nomor ditampilkan`;
  renderLocks();
}
async function refresh() {
  if (refreshing) {
    refreshAgain = true;
    return;
  }
  if (busy) return;
  refreshing = true;
  try {
    const response = await fetch(
      "/api/state" + (selected ? "?session_id=" + selected : ""),
      { cache: "no-store", signal: AbortSignal.timeout(6000) },
    );
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Data belum dapat dimuat.");
    state = data;
    lastSuccess = Date.now();
    $("error-banner").hidden = true;
    $("connection").textContent = "Tersambung · data lokal";
    $("connection").classList.remove("offline");
    render();
  } catch (error) {
    showError(
      error.message || "Server belum tersambung. Data lama tetap ditampilkan.",
    );
  } finally {
    refreshing = false;
    if (refreshAgain) {
      refreshAgain = false;
      refresh();
    }
  }
}
async function sendPending() {
  if (!pending || busy) return;
  busy = true;
  renderLocks();
  const item = pending;
  try {
    const response = await fetch("/api/mutate", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": item.key,
      },
      body: JSON.stringify(item.payload),
      signal: AbortSignal.timeout(8000),
    });
    const data = await response.json();
    if (!response.ok) {
      if (response.status < 500) {
        outbox.clear(item.key);
        pending = null;
        throw new Error(data.error || "Permintaan ditolak.");
      }
      throw new Error(
        data.error || "Jawaban belum pasti. Gunakan Coba ulang permintaan.",
      );
    }
    outbox.clear(item.key);
    pending = null;
    if (data.result.action === "create" || data.result.action === "demo")
      selected = data.result.session_id;
    if (data.result.action === "issue") {
      $("alias").value = "";
      $("issued-code").textContent = data.result.code;
      $("issued").hidden = false;
    }
    closeDialogs();
    toast(
      data.replayed
        ? "Permintaan yang sama telah dipastikan, tanpa dijalankan ulang."
        : data.result.code
          ? `${data.result.code} · tindakan tersimpan.`
          : "Perubahan berhasil disimpan.",
    );
  } catch (error) {
    if (pending) {
      closeDialogs();
      $("pending-text").textContent =
        error.message +
        " Gunakan tombol Coba ulang permintaan; jangan membuat permintaan baru.";
    } else if ($("session-dialog").open) {
      $("session-error").textContent = error.message;
      $("session-error").hidden = false;
    }
    toast(
      pending
        ? "Jawaban belum pasti. Permintaan tersimpan untuk dicoba ulang."
        : error.message,
      true,
    );
  } finally {
    busy = false;
    renderLocks();
    await refresh();
  }
}
async function mutate(payload) {
  if (locked())
    return toast(
      "Pastikan permintaan sebelumnya dan koneksi terlebih dahulu.",
      true,
    );
  try {
    pending = outbox.stage(payload);
    await sendPending();
  } catch (error) {
    toast("Permintaan belum dikirim: " + error.message, true);
    renderLocks();
  }
}
function ask(payload, title, description, label = "Lanjutkan") {
  confirmPayload = payload;
  $("confirm-title").textContent = title;
  $("confirm-description").textContent = description;
  $("confirm-action").textContent = label;
  $("confirm-dialog").showModal();
}
$("confirm-action").addEventListener("click", () => {
  const payload = confirmPayload;
  $("confirm-dialog").close();
  if (payload) mutate(payload);
});
$("confirm-dialog").addEventListener("close", () => {
  confirmPayload = null;
});
function openSession() {
  $("session-form").reset();
  $("session-day").value = state?.today || "";
  $("session-error").hidden = true;
  $("session-dialog").showModal();
}
$("new-session").addEventListener("click", openSession);
$("start-session").addEventListener("click", openSession);
$("session-form").addEventListener("submit", (event) => {
  event.preventDefault();
  mutate({
    action: "create",
    title: $("session-name").value,
    day: $("session-day").value,
    counters: $("counter-names")
      .value.split(/\r?\n/u)
      .map((s) => s.trim())
      .filter(Boolean),
  });
});
$("issue-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (state?.selected)
    mutate({
      action: "issue",
      session_id: state.selected.id,
      alias: $("alias").value,
    });
});
$("load-demo").addEventListener("click", () =>
  ask(
    { action: "demo" },
    "Coba data sintetis?",
    "Lima nomor dan dua loket dibuat pada database kosong. Tidak ada data pengunjung nyata.",
    "Muat contoh",
  ),
);
$("close-session").addEventListener("click", () =>
  ask(
    { action: "close", session_id: state.selected.id },
    "Tutup sesi layanan?",
    "Tidak boleh ada nomor yang masih menunggu atau dilayani. Sesi yang ditutup menjadi arsip dan tidak bisa dibuka ulang.",
    "Ya, tutup sesi",
  ),
);
$("retry-pending").addEventListener("click", sendPending);
$("check-pending").addEventListener("click", refresh);
$("reload-state").addEventListener("click", refresh);
$("session-select").addEventListener("change", () => {
  selected = Number($("session-select").value) || null;
  $("issued").hidden = true;
  refresh();
});
$("ticket-search").addEventListener("input", () => state && renderTickets());
$("status-filter").addEventListener("change", () => state && renderTickets());
$("help-button").addEventListener("click", () => $("help-dialog").showModal());
window.addEventListener("storage", (event) => {
  if (event.key === "loketkecil.pending.v1") {
    try {
      pending = outbox.read();
      renderLocks();
    } catch {
      outboxBroken = true;
      renderLocks();
    }
  }
});
try {
  outbox = new Outbox(window.localStorage);
  pending = outbox.read();
} catch {
  outboxBroken = true;
}
renderLocks();
refresh();
setInterval(() => {
  renderLocks();
  refresh();
}, 3000);
