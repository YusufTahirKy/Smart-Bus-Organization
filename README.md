# İETT Dinamik Rotalama Merkezi

Bu proje, İstanbul'daki İETT otobüs hatlarının anlık ve tahmini yolcu yoğunluklarını analiz eden, bu yoğunluklara göre yapay zeka destekli kararlar vererek otobüsleri dinamik olarak en çok ihtiyaç duyulan hatlara yönlendiren (rerouting) kapsamlı bir sistemdir.

## Özellikler
- **Gerçek Zamanlı Yoğunluk Takibi:** SQLite tabanlı veritabanı ile hatların anlık durumlarını, seferdeki otobüs sayılarını ve bekleyen yolcu tahminlerini takip eder.
- **Makine Öğrenimi (AI) ile Gelecek Tahmini:** Random Forest Regressor kullanılarak `T+1` (bir sonraki saat) için yolcu tahmini yapılır. Rotalama algoritması, sadece mevcut anı değil, gelecekteki yoğunluğu da hesaba katarak proaktif davranır.
- **Gelişmiş Rotalama Motoru:** Min/Max otobüs servis garantisi kurallarına uyarak atıl otobüsleri tespit eder ve yoğun hatlara çeker.
- **Sürücü Geri Bildirimi:** Şoförlerin gönderdiği anlık "Dolu" / "Boş" sinyallerini Rolling Window mantığıyla değerlendirerek yoğunluk skorlarına (%25 etkiyle) dahil eder.
- **Modern Web Arayüzü (Dashboard):** 
  - Koyu ve Açık (Dark/Light) Tema desteği.
  - Mobil cihazlarla tam uyumlu (Responsive) tasarım.
  - **Rota Analizi:** 806 İETT hattı için 24 saatlik yoğunluk gidişatını interaktif Chart.js grafikleriyle sunar.
  - **Bildirimler:** Tüm sistem loglarını ve rotalama geçmişini listeler.

---

## 🛠️ Kurulum ve Çalıştırma (Geliştiriciler İçin)

Projenin çalışması için bilgisayarınızda **Python 3.8+** yüklü olmalıdır.

### 1. Gerekli Kütüphanelerin Kurulumu
Terminali açın ve proje dizinine giderek aşağıdaki komutu çalıştırın:
```bash
pip install -r requirements.txt
```

### 2. Veritabanının ve Verilerin Hazırlanması (İlk Kurulum)
Eğer sistemi ilk kez kuruyorsanız veya ham CSV verisinden (`hourly_passengers.csv`) güncel veritabanını oluşturmak istiyorsanız şu komutu çalıştırın:
*(Not: Veri setinin boyutuna göre bu işlem 1-2 dakika sürebilir. Koordinat eksiklikleri varsa otomatik tamamlanır.)*
```bash
python data_aggregation.py
```
*Geliştirme veya UI testi yapmak istiyorsanız devasa veri işlemek yerine hızlıca `python generate_dummy_data.py` komutuyla test verisi de oluşturabilirsiniz.*

### 3. Yapay Zeka Modelinin Eğitilmesi
Sistemin gelecek tahminlerini yapabilmesi için makine öğrenimi modelinin eğitilmesi gerekir:
```bash
python train_model.py
```
*(Bu işlem `models/` klasörü altına `route_regressor.pkl` ve `route_encoder.pkl` dosyalarını oluşturacaktır.)*

### 4. Sistemi ve Arayüzü Başlatma
Arka plan (API) sunucusunu ve web arayüzünü tek bir komutla ayağa kaldırmak için:
```bash
python api.py
```

### 5. Arayüze Erişim
Sistem başlatıldıktan sonra tarayıcınızı açın ve şu adrese gidin:
👉 **http://localhost:8000**

---

## 📂 Proje Yapısı
- `api.py`: FastAPI sunucusu. REST endpoint'leri sağlar, arayüzü sunar ve periyodik olarak arka planda rotalama motorunu tetikler.
- `database.py`: SQLite veritabanı (system.db) bağlantılarını ve tablo şemalarını yönetir.
- `data_aggregation.py`: Ham veriyi işler, gruplar ve veritabanını doldurur.
- `train_model.py`: Geçmiş verileri kullanarak Random Forest Regressor modelini eğitir.
- `inference.py`: Eğitilmiş modeli kullanarak anlık tahmin (T+1) üretir.
- `rerouting.py`: Yoğunluk skorlarını ve sürücü sinyallerini birleştirerek otobüs kaydırma (reroute) mantığını çalıştırır.
- `static/`: Web arayüzünün barındırıldığı klasör (`index.html`, `style.css`, `app.js`).
- `models/`: Eğitilmiş makine öğrenimi modellerinin kaydedildiği dizin.
- `data/`: SQLite veritabanı dosyasının (system.db) tutulduğu dizin.
