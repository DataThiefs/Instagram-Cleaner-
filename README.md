# InsCleaner — Instagram Eski Hikaye & DM Temizleyici (PC + Mobil)

Hem **PC** hem **Mobil** cihazlarda çalışabilen, anti-ban korumalı Instagram Arşiv Hikaye ve DM temizleme aracı.

## Özellikler
- **Esnek Giriş:** `sessionid` çerezi (şifresiz, en güvenli), Kullanıcı Adı + Şifre (+ 2FA) ve risksiz test için **Demo Modu**.
- **DM Sohbet Temizleyici:** Sohbetleri filtreleme, seçili sohbetleri toplu silme ve opsiyonel olarak kendi mesajlarını geri alma (Unsend).
- **Kelime Bazlı DM Arama & Silme:** Arattığın kelimeyi (örn. `iban`, `adres`, `şifre`) tüm DM mesajlarında tarar, eşleşen kendi mesajlarını seçip geri alır.
- **Arşiv Hikaye (Story Archive) Temizleyici:** Eski hikayeleri tarih filtresiyle (30 gün+, 6 ay+, 1 yıl+ veya özel tarih) listeleme ve toplu silme.
- **All Clean (Tam Temizlik):** Tek işlemde tüm DM'leri ve/veya arşivlenmiş hikayeleri temizleme + **Koruma Listesi (Whitelist)** + **Önizleme (Dry-Run)** modu.
- **Anti-Ban Koruması:** Ayarlanabilir rastgele bekleme süreleri, Duraklat / Devam Et / Durdur kontrolleri ve Instagram hız sınırı algılandığında otomatik durdurma.
- **Tarayıcı Eklentisi (`extension/`):** Chrome / Edge / Kiwi Browser (Android) üzerinde tek tıkla `sessionid` çerezini okuyup panele aktarır.

## Kurulum ve Çalıştırma (PC)
```powershell
# Sanal ortam oluştur (ilk seferde)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Uygulamayı başlat
.\.venv\Scripts\python.exe run.py
```
Tarayıcıda aç: `http://127.0.0.1:8000`

## Mobilden Kullanım
1. **Wi-Fi (PWA) Yöntemi:** PC'de `run.py` çalıştırıldığında terminalde yazan `Mobil (Wi-Fi): http://192.168.x.x:8000` adresini telefonunun tarayıcısında aç ve **"Ana Ekrana Ekle"** diyerek uygulama gibi kullan.
2. **Doğrudan Android (Termux):** Termux içinde `pkg install python`, `pip install -r requirements.txt`, `python run.py` çalıştırıp telefondan `http://127.0.0.1:8000` adresini aç.

## Tarayıcı Eklentisini Yükleme (Opsiyonel)
1. Chrome/Edge (veya Android Kiwi Browser) adres çubuğuna `chrome://extensions` yaz.
2. **Geliştirici Modu (Developer Mode)** seçeneğini aç.
3. **Paketlenmemiş öğe yükle (Load unpacked)** deyip `extension/` klasörünü seç.
4. `instagram.com` açıkken eklentiye tıkla ve **"Session ID ile Paneli Aç"** butonuna bas.
