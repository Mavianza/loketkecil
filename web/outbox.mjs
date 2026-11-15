export const STORAGE_KEY = "loketkecil.pending.v1";
export class Outbox {
  constructor(storage, makeKey = () => crypto.randomUUID()) {
    this.storage = storage;
    this.makeKey = makeKey;
  }
  read() {
    const raw = this.storage.getItem(STORAGE_KEY);
    if (raw === null) return null;
    const item = JSON.parse(raw);
    if (
      !item ||
      typeof item !== "object" ||
      Object.keys(item).sort().join(",") !== "key,payload" ||
      typeof item.key !== "string" ||
      !/^[A-Za-z0-9_-]{8,80}$/.test(item.key) ||
      !item.payload ||
      typeof item.payload !== "object" ||
      Array.isArray(item.payload) ||
      typeof item.payload.action !== "string"
    )
      throw new Error(
        "Pengingat permintaan browser tidak valid. Periksa status server dan cadangkan data sebelum membersihkan penyimpanan browser.",
      );
    return item;
  }
  stage(payload) {
    if (this.read())
      throw new Error("Masih ada permintaan yang harus dipastikan.");
    const item = { key: this.makeKey(), payload: structuredClone(payload) };
    this.storage.setItem(STORAGE_KEY, JSON.stringify(item));
    return item;
  }
  clear(key) {
    const active = this.read();
    if (active && active.key !== key)
      throw new Error(
        "Permintaan browser berubah di tab lain. Muat ulang untuk memeriksanya.",
      );
    this.storage.removeItem(STORAGE_KEY);
  }
}
