# 3D Model Arşivi

`3d models/` klasörünü tarayıp modelleri otomatik kategorilere ayıran, sunucu tarafında önizleme üreten ve tarayıcıda 3D gösteren kişisel model arşivi. Ziyaretçiler arşivi gezer; yönetici girişiyle yükleme, düzenleme, gizleme ve paylaşım bağlantısı oluşturma yapılır.

## Özellikler

- **Akıllı gruplama:** Klasör + `files`/`V2`/`UPDATES`/`STL SINGLES` gibi yardımcı alt klasörler tek model olur. `isim20250910-1-abc123/yazar/isim` indirme sarmalayıcıları sadeleşir ve aradaki klasör tasarımcı olarak kaydedilir. Doğrudan dosyası olmayan çok klasörlü paketler koleksiyona ayrılır. Kökteki açılmamış zip'ler de model olarak listelenir.
- **Doğru kategoriler:** 18 kategori; kelime sınırlı, Türkçe karakter duyarsız ağırlıklı puanlama (başlık, koleksiyon, dosya adları, README ve 3MF başlığı/açıklaması). Yönetici her modelin kategorisini tek tıkla değiştirebilir; “Otomatiğe dön” ile geri alabilir.
- **Zengin bilgi:** Thingiverse README'lerinden başlık, tasarımcı, kaynak ve özet; LICENSE'tan lisans kodu (CC BY-SA vb.); Printables PDF'lerinden kaynak bağlantısı; 3MF içinden tasarımcı, açıklama, lisans ve dilimleyici baskı profili (yazıcı, katman, doluluk, malzeme, destek).
- **Önizleme ve ölçüler:** Küçük resimler sunucuda (numpy + Pillow, GPU gerekmez) bir kez üretilir. Her model için boyut (mm), hacim (cm³) ve üçgen sayısı hesaplanır. Fotoğraf varsa kapak olarak kullanılır, yönetici kapağı değiştirebilir.
- **3D görüntüleyici:** STL, 3MF (Bambu/Orca/Creality çok dosyalı 3MF dahil), OBJ, PLY, GLB/GLTF. Filament rengi önizleme, tel kafes, ölçü kutusu, tam ekran. Büyük 3MF/OBJ/PLY dosyaları sunucuda kompakt biçime çevrilip önbelleğe alınır; çok büyük parçalar tıklayınca yüklenir.
- **Yükleme:** Sürükle-bırak, klasör seçimi, 8 MB'lık parçalarla kesintiye dayanıklı yükleme (Cloudflare 100 MB sınırına takılmaz). ZIP arşivleri güvenli biçimde açılır. Kategori ve etiketler dosya adından canlı önerilir. Var olan modele dosya eklenebilir.
- **Paylaşım:** Model başına `/s/<token>` bağlantıları; süre (1 gün–1 yıl veya süresiz), indirme izni, not, görüntülenme sayısı, iptal. Gizli modellerde ve özel arşivde de çalışır. QR kod, WhatsApp/Telegram/e-posta ve zengin bağlantı önizlemesi (Open Graph görseli). Herkese açık modeller `/m/<id>` ile de paylaşılabilir.
- **Yönetim:** Öne çıkanlar, basıldı işareti, özel not, ziyaretçilerden gizleme, 18+ işareti (adlardan otomatik algılanır, varsayılan olarak ziyaretçilere gizlenir), çöp kutusu (dosyalar silinmez, `.trash/` klasörüne taşınır), ayarlar (site adı, arşiv gizliliği, ziyaretçi indirmeleri, şifre değiştirme, bakım).
- **Arayüz:** Açık/koyu tema, anlık istemci tarafı arama ve filtreler (URL'e yazılır, paylaşılabilir), sonsuz kaydırma, klavye kısayolları (`Ctrl+K` / `/` arama, `←` `→` modeller arası, `Esc` kapat, `U` yükle), mobil uyumlu yerleşim. Tüm varlıklar yerel; internet bağlantısı gerektirmez.

## Çalıştırma

```bash
pip install -r requirements.txt
python app.py set-admin-password   # yönetici şifresini belirle (bir kez)
python app.py
```

Varsayılan adres `http://localhost:5000`. İlk açılışta katalog taranır, önizlemeler arka planda üretilir. Klasöre dosya eklendiğinde değişiklik yaklaşık bir dakika içinde otomatik algılanır.

Diğer komutlar:

```bash
python app.py scan                  # kütüphaneyi hemen tara
python app.py thumbnails            # eksik önizleme ve ölçüleri üret (--all: hepsini yeniden)
echo 'yeni-sifre' | python app.py set-admin-password --stdin
```

Yönetici şifresi yalnızca hash olarak `db.json` içinde saklanır; depoya hiçbir şifre yazılmaz.

## Ortam değişkenleri

| Değişken | Açıklama | Varsayılan |
| --- | --- | --- |
| `MODEL_MANAGER_HOST` / `MODEL_MANAGER_PORT` | Dinlenecek adres ve port | `127.0.0.1` / `5000` |
| `MODEL_MANAGER_DEBUG` | Flask hata ayıklama modu | kapalı |
| `MODEL_MANAGER_MODELS_DIR` | Model klasörü | `./3d models` |
| `MODEL_MANAGER_DATA_DIR` | `db.json`, `thumbnails/`, `.uploads/`, `.trash/`, `.secret_key` konumu | uygulama klasörü |
| `MODEL_MANAGER_WORKERS` | gunicorn altında arka plan işçilerini (izleyici + önizleme kuyruğu) başlat | kapalı |
| `MODEL_MANAGER_TRUST_PROXY` | Ters vekil başlıklarına (X-Forwarded-*) güven | kapalı |
| `MODEL_MANAGER_SECURE_COOKIES` | Oturum çerezini yalnızca HTTPS'te gönder | kapalı |
| `MODEL_MANAGER_SECRET_KEY` | Oturum imza anahtarı (verilmezse `.secret_key` dosyasında üretilir) | otomatik |

## Proje yapısı

```text
app.py          Flask uygulaması: API, oturum, yükleme, paylaşım, arka plan işçileri, CLI
catalog.py      Kütüphane tarama, gruplama, isim temizleme, README/LICENSE/3MF metadata
categories.py   Kategori taksonomisi ve sınıflandırıcı
meshes.py       STL/3MF/OBJ/PLY okuma, ölçü, yazılım render'ı, kompakt mesh (ayrı süreçte çalışır)
templates/      Sayfa şablonları ve ikon sprite'ı
static/         Arayüz (css, js) ve yerel kütüphaneler (Three.js, Inter, QR)
tests/          Birim ve API testleri
deploy/         Docker Compose, Nginx ve sertifika yenileme dosyaları
```

Veritabanı (`db.json`) kullanıcı verisini (kategori/başlık düzeltmeleri, etiketler, notlar, gizlilik, paylaşımlar, ayarlar) ve son tarama kataloğunu tutar. Eski sürümün veritabanı ilk açılışta otomatik olarak yeni şemaya taşınır ve `db.v1-backup-*.json` olarak yedeklenir.

## API özeti

- `GET /api/library` — görünür modellerin kart listesi ve istatistikler
- `GET /api/models/<id>` — model detayı · `PATCH` düzenle · `DELETE` çöp kutusuna taşı (yönetici)
- `GET /api/models/<id>/download` — tüm dosyalar ZIP olarak (akış halinde)
- `GET /api/file/<yol>` · `/api/mesh/<yol>` · `/api/preview/<yol>` · `/api/thumb/<id>` · `/api/og/<id>`
- `POST /api/auth/login` · `POST /api/auth/logout` · `POST /api/auth/password`
- `POST /api/uploads` → `PUT /api/uploads/<id>/<dosya>` (parça, `X-Upload-Offset`) → `POST /api/uploads/<id>/complete`
- `GET /api/shares` · `POST /api/models/<id>/shares` · `PATCH`/`DELETE /api/shares/<token>` · sayfa: `/s/<token>`
- `GET`/`PATCH /api/settings` · `POST /api/scan` · `GET /api/admin/status` · `POST /api/admin/thumbnails`

Değişiklik yapan tüm istekler `X-CSRF-Token` başlığı ister; token sayfadaki `boot` verisinde ve `/api/session` yanıtında bulunur.

## Geliştirme

```bash
python -m unittest -v
ruff check .
```

`static/vendor/three/examples/js/loaders/3MFLoader.js` dosyasına 3MF Production Extension (`p:path`) bileşen desteği için küçük bir yerel yama uygulanmıştır.
