import test from "node:test";
import assert from "node:assert/strict";
import { Outbox, STORAGE_KEY } from "../web/outbox.mjs";
function storage() {
  const items = new Map();
  return {
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => items.set(key, value),
    removeItem: (key) => items.delete(key),
  };
}
test("permintaan dan kunci tetap sama setelah sesi UI dimuat ulang", () => {
  const s = storage(),
    a = new Outbox(s, () => "request-key-001"),
    command = { action: "issue", session_id: 1, alias: "Contoh" };
  const item = a.stage(command);
  command.alias = "Berubah";
  const b = new Outbox(s);
  assert.deepEqual(b.read(), item);
  assert.equal(b.read().payload.alias, "Contoh");
});
test("permintaan kedua ditolak selama jawaban pertama belum dipastikan", () => {
  const s = storage(),
    box = new Outbox(s, () => "request-key-001");
  box.stage({ action: "demo" });
  assert.throws(() => box.stage({ action: "demo" }), /Masih ada/);
});
test("kegagalan simpan tidak menghasilkan permintaan siap kirim", () => {
  const s = storage();
  s.setItem = () => {
    throw new Error("quota");
  };
  const box = new Outbox(s, () => "request-key-001");
  assert.throws(() => box.stage({ action: "demo" }), /quota/);
  assert.equal(box.read(), null);
});
test("clear kunci lama tidak menghapus permintaan tab lain", () => {
  const s = storage(),
    box = new Outbox(s, () => "request-key-001");
  box.stage({ action: "demo" });
  s.setItem(
    STORAGE_KEY,
    JSON.stringify({ key: "request-key-002", payload: { action: "demo" } }),
  );
  assert.throws(() => box.clear("request-key-001"), /tab lain/);
  assert.equal(box.read().key, "request-key-002");
});
test("data pengingat rusak tidak dihapus otomatis", () => {
  const s = storage();
  s.setItem(STORAGE_KEY, "rusak");
  assert.throws(() => new Outbox(s).read());
  assert.equal(s.getItem(STORAGE_KEY), "rusak");
});
test("jawaban yang dipastikan boleh membersihkan pengingat yang cocok", () => {
  const s = storage(),
    box = new Outbox(s, () => "request-key-001");
  box.stage({ action: "demo" });
  box.clear("request-key-001");
  assert.equal(box.read(), null);
});
