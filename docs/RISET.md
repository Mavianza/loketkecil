# Riset masalah: giliran pada meja layanan kecil

Tanggal penelusuran: **16 November 2026 (WITA)**. Lokasi konteks: Kota Mataram, Lombok. Riset hanya memakai halaman publik; tidak ada data pengunjung nyata yang dikumpulkan.

## Bukti dan cakupannya

| Sumber independen | Tanggal sumber | Temuan yang dipakai | Batas cakupan |
| --- | --- | --- | --- |
| [Dukcapil Kota Mataram — Perekaman KTP Elektronik](https://dukcapil.mataramkota.go.id/layanan/perekaman-ktp-elektronik) | Halaman diperbarui 29 Juli 2026 | Alur layanan menyebut pengambilan nomor antrean sebelum tahapan pelayanan berikutnya. | Menunjukkan penggunaan giliran bernomor dalam satu layanan; tidak mengukur lama tunggu atau menyatakan antrean masih manual. |
| [ANTARA NTB — Layanan adminduk di Mal Pelayanan Publik Mataram meningkat](https://mataram.antaranews.com/berita/475481/layanan-adminduk-di-mal-pelayanan-publik-mataram-meningkat) | 1 Agustus 2025, 17.57 WIB | Keterangan petugas pada liputan menyebut sekitar 50–60 pengunjung per hari. | Angka historis pada lokasi dan periode peliputan; bukan pengukuran November 2026 atau data milik aplikasi. |

## Hambatan yang dibatasi

Pengelola meja layanan kecil perlu mengetahui nomor yang menunggu, loket yang kosong, dan pengunjung yang sudah dipanggil. Program difokuskan pada pencatatan satu antrean bersama, bukan pemodelan seluruh prosedur layanan publik.

**Temuan bersumber:** nomor antrean merupakan bagian dari alur layanan lokal; ada konteks layanan dengan puluhan kunjungan harian pada laporan historis.

**Asumsi desain:** meja kegiatan kampus atau layanan kecil mungkin terbantu oleh satu komputer dengan layar kedua. Belum diketahui apakah pengguna tersebut menghadapi panggilan ganda, memerlukan 1–4 loket, atau akan memilih aplikasi ini. Penerapan lokal masih hipotesis.

**Data sintetis:** contoh lima pengunjung, skenario tambahan A006, judul sesi, seluruh alias dan database tes dibuat untuk pengembangan. Tidak berasal dari Dukcapil, ANTARA, atau instansi mana pun.

## Hubungan kebutuhan dan fitur

| Kebutuhan yang ditargetkan | Fitur | Pemeriksaan yang relevan |
| --- | --- | --- |
| Petugas mengetahui giliran berikutnya | FIFO bersama dan tombol panggil pada loket kosong | Dua loket memanggil bersamaan: memperoleh dua nomor berbeda |
| Pengunjung belum hadir lalu kembali | Lewati dan masukkan ulang ke akhir antrean | A003 yang masuk ulang dipanggil setelah A004–A006 |
| Pengunjung dapat melihat nomor panggilan | Layar besar tanpa alias, pembaruan otomatis | API layar diperiksa tanpa alias; tampilan dua loket diperiksa di browser |
| Petugas ragu apakah tindakan tersimpan | Transaksi SQLite, kunci idempotensi dan outbox browser | Kegagalan catatan membatalkan transaksi; permintaan tetap dapat dicoba ulang setelah reload |
| Penutupan kegiatan tetap memiliki catatan | Arsip, CSV dan cadangan SQLite | Penutupan dengan antrean aktif ditolak; snapshot cadangan dapat dibuka kembali |

Pemilihan fitur merupakan keputusan desain dari hambatan di atas. Riset tidak membuktikan adanya insiden tersebut pada instansi yang dirujuk. Tidak ada afiliasi, integrasi, klaim adopsi, atau klaim pengurangan waktu tunggu.
