# Catatan pengujian rilis 1.0.0

Dilaksanakan pada **16 November 2026 (WITA)** di lingkungan Linux dengan Python, SQLite bawaan, Node.js, dan Chromium. Semua data bersifat sintetis. Pemeriksaan tidak dijalankan dalam job yang memegang token penerbit GitHub.

## Pemeriksaan otomatis

| Perintah dari root proyek | Hasil aktual |
| --- | --- |
| `python3 -m unittest discover -s tests -v` | 26 tes lulus; memakai HTTP server nyata pada loopback dan database SQLite sementara |
| `node --test tests/outbox.test.mjs` | 6 tes lulus |
| `npm run check` | Sintaks `operator.mjs`, `display.mjs`, dan `outbox.mjs` valid |

Integrasi Python mencakup alur buka sesi → terbitkan → panggil → lewati → masuk ulang → selesai → arsip, penerbitan bersamaan, dua loket memanggil bersamaan, dua permintaan pada satu loket, kunci idempotensi yang sama, respons tidak dibaca lalu percobaan ulang setelah database dibuka kembali, kegagalan penulisan event, versi tombol yang usang, penutupan dengan antrean aktif, data contoh, privasi respons layar, CSV, backup/restore, skema asing, database rusak, validasi JSON serta Host/Origin.

Tes outbox memeriksa kunci/payload tetap sama setelah objek UI dibuat ulang, permintaan kedua ditolak, kegagalan penyimpanan lokal, clear dengan kunci usang, data pengingat rusak, dan pembersihan setelah hasil dipastikan. Tes ini memakai penyimpanan tiruan di Node; ketahanan setelah reload browser diperiksa terpisah di bawah.

## Pemeriksaan browser dengan backend nyata

1. Memuat contoh lima nomor: A001 selesai, A002 dilayani Loket 1, A003–A005 menunggu.
2. Memasang trigger pengujian SQLite yang menggagalkan penulisan event `call`, lalu menekan **Panggil berikutnya** pada Loket 2. Respons gagal menampilkan pengingat permintaan; A003 tetap menunggu dan Loket 2 tetap kosong. Jumlah event panggil tetap dua.
3. Memuat ulang halaman: permintaan tertunda tetap tampil. Menghapus trigger pengujian lalu menekan **Coba ulang permintaan**: A003 dilayani Loket 2; database memiliki tepat satu event panggil untuk A003. Pengingat hilang.
4. Menerbitkan A006, melewati A003 lalu memasukkannya ulang. Panggilan berikutnya memperoleh A004; urutan akhir antrean menjadi A005, A006, A003. Setelah A002 selesai dan Loket 1 memanggil kembali, loket itu memperoleh A005.
5. Mencari A003 dengan filter Menunggu: hanya baris A003 terlihat. Menghapus pencarian/filter mengembalikan semua baris.
6. Mencoba menutup sesi yang masih memiliki antrean: ditolak dan sesi tetap aktif.
7. Mengunduh CSV dan cadangan melalui tombol browser sebelum pemanggilan A005. CSV berisi header serta enam baris nomor; cadangan dibuka dengan SQLite, `PRAGMA integrity_check` menghasilkan `ok`, dan keenam status sesuai saat pengunduhan.
8. Membuka layar panggilan terpisah: A005 pada Loket 1, A004 pada Loket 2, berikutnya A006 dan A003. Alias tidak ada pada tampilan. Screenshot panel dan layar disertakan pada README.

Trigger pengujian sudah dihapus dan database pengujian tidak disertakan dalam rilis. Skenario browser di atas menguji rollback lalu retry; skenario respons hilang sesudah commit dibuktikan oleh tes integrasi Python, bukan oleh simulasi browser ini.

## Batas validasi

Belum dilakukan uji lapangan, uji beban produksi, uji peluncur pada Windows/macOS, pemeriksaan Safari/Firefox, simulasi kehilangan daya fisik, atau pemulihan media rusak. Pengujian konkurensi membuktikan skenario yang dijalankan, bukan jaminan untuk beban tak terbatas. Pengingat `localStorage` mensyaratkan satu tab petugas aktif per browser; tes tidak mengklaim koordinasi atomik antar-tab.
