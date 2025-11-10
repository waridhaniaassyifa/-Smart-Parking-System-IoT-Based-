# 🚀 Cara Menjalankan Smart Parking System

## A. Mode Lokal (HP & PC di Wi-Fi yang sama)

1. **Jalankan server:**
```bash
   python app.py
```

2. **Akses dari PC:**
   - Buka browser: `http://localhost:5000`

3. **Akses dari HP:**
   - Pastikan HP & PC di Wi-Fi yang sama
   - Di HP, buka browser: `http://[IP_LOKAL]:5000`
   - IP lokal akan muncul di console (contoh: `http://192.168.1.100:5000`)

4. **Generate QR Code:**
   - Klik "Tambah Kamera" → pilih "Mobile Camera"
   - Scan QR code dengan HP
   - QR akan otomatis pakai IP lokal

---

## B. Mode Online (Cloudflare Tunnel)

### Kenapa butuh tunnel?
- HP bisa akses dari mana saja (tidak perlu Wi-Fi yang sama)
- Gratis dan mudah dipakai
- Tidak perlu port forwarding router

### Langkah-langkah:

1. **Install Cloudflared** (hanya sekali):
```bash
   # Windows
   winget install --id Cloudflare.cloudflared
   
   # Mac
   brew install cloudflare/cloudflare/cloudflared
   
   # Linux
   wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb
```

2. **Jalankan Flask server** (terminal 1):
```bash
   python app.py
```

3. **Jalankan Cloudflare tunnel** (terminal 2):
```bash
   cloudflared tunnel --url http://localhost:5000
```

4. **Copy URL public** yang muncul:
```
   Your quick Tunnel has been created! Visit it at:
   https://abc-def-123.trycloudflare.com
```

5. **Set URL di aplikasi:**
   - Buka `http://localhost:5000`
   - Klik tombol "⚙️ Tunnel"
   - Paste URL: `https://abc-def-123.trycloudflare.com`
   - Klik "Simpan URL"

6. **Generate QR Code:**
   - Klik "Tambah Kamera" → pilih "Mobile Camera"
   - QR code sekarang pakai URL public
   - Scan dari HP mana saja (tidak perlu Wi-Fi sama)

---

## C. Tips & Troubleshooting

### QR code tidak bisa dibuka dari HP:
1. Cek firewall Windows → Allow port 5000
2. Pastikan PC & HP di Wi-Fi yang sama (mode lokal)
3. Atau gunakan Cloudflare tunnel (mode online)

### Cloudflare tunnel mati:
- URL berubah setiap restart `cloudflared`
- Update URL baru di tombol "⚙️ Tunnel"
- Atau pakai tunnel permanent (lihat dokumentasi Cloudflare)

### Camera tidak muncul:
- Pastikan browser support WebRTC (Chrome/Safari)
- Allow camera permission di HP

---

## D. Perbandingan Mode

| Fitur | Mode Lokal | Mode Online (Tunnel) |
|-------|-----------|---------------------|
| Setup | Mudah | Butuh install cloudflared |
| Akses | Hanya Wi-Fi sama | Dari mana saja |
| Kecepatan | Sangat cepat | Sedikit delay |
| Keamanan | Aman (lokal) | Aman (HTTPS) |
| Biaya | Gratis | Gratis |

---

## E. Struktur File
```
project/
├── app.py              # Backend Flask (SUDAH DIMODIFIKASI)
├── templates/
│   ├── index.html      # Dashboard (SUDAH DIMODIFIKASI)
│   └── mobile.html     # Mobile camera page
└── README_DEPLOYMENT.md # (INI)
```

---

## F. Command Quick Reference
```bash
# Jalankan mode lokal
python app.py

# Jalankan mode online (buka 2 terminal)
# Terminal 1:
python app.py

# Terminal 2:
cloudflared tunnel --url http://localhost:5000
```
