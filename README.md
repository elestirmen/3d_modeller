# 3D Model Yöneticisi

Yerel `3d models/` klasörünü tarayan, modelleri kataloglayan ve web arayüzü üzerinden filtreleme, etiketleme, favorileme ve 3D önizleme sağlayan küçük bir Flask uygulaması.

## Özellikler

- `3d models/` klasörünü tarayıp proje veya tekil dosya olarak kataloglar.
- Artımlı taramada silinen kayıtları da temizleyerek katalogu senkron tutar.
- Dosya ve klasör isimlerinden otomatik etiket önerileri üretir.
- İsim, etiket, format ve favori durumuna göre filtreleme yapar.
- `README`, `LICENSE`, görsel, `CAD`, `G-code`, arşiv ve doküman dosyalarını maker metadata olarak kataloglar.
- Model bazlı not, favori ve yazdırıldı durumu saklar.
- STL ve 3MF dosyaları için Three.js tabanlı önizleme sunar, görsel referansları modal içinde gösterir.
- Three.js bağımlılıklarını yerel `static/vendor/` altından servis ederek internet olmadan çalışır.

## Çalıştırma

```bash
pip install -r requirements.txt
python app.py
```

Varsayılan adres `http://localhost:5000` olur.

İlk açılışta katalog taranır. Dosya sisteminde değişiklik yaptıktan sonra arayüzdeki `Yenile` düğmesi yalnızca farkları işler, `Tam Tara` ise tüm katalogu baştan üretir.

## Çevre Değişkenleri

- `MODEL_MANAGER_HOST`: Flask host değeri. Varsayılan `127.0.0.1`
- `MODEL_MANAGER_PORT`: Flask port değeri. Varsayılan `5000`
- `MODEL_MANAGER_DEBUG`: `1`, `true`, `yes` veya `on` verilirse debug açılır

Örnek:

```bash
MODEL_MANAGER_DEBUG=1 python app.py
```

## Proje Yapısı

```text
3d_modeller/
├── app.py
├── requirements.txt
├── db.json
├── 3d models/
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/index.html
└── tests/test_app.py
```

## API

- `GET /api/models`: Model listesi. `q`, `tag`, `format`, `sort`, `fav`, `has_readme`, `has_license`, `has_cad`, `has_gcode`, `multipart` parametrelerini destekler.
- `POST /api/models/<id>/tags`: Etiketleri günceller.
- `POST /api/models/<id>/favorite`: Favori durumunu değiştirir.
- `POST /api/models/<id>/note`: Notu günceller.
- `POST /api/models/<id>/printed`: Yazdırıldı durumunu değiştirir.
- `GET /api/tags`: Kullanılan etiketleri ve sayılarını döner.
- `POST /api/scan`: Klasörü yeniden tarar.
- `GET /api/stats`: Özet istatistikleri döner.
- `GET /api/file/<path>`: Desteklenen model ve maker asset dosyalarını servis eder.
- `GET /api/preview/<path>`: 3MF dosyaları için gömülü önizleme görselini döner.

## Geliştirme

Test:

```bash
python -m unittest -v
```

Lint:

```bash
ruff check .
```

Repo artık `.editorconfig` ve `pyproject.toml` ile temel editör ve lint kurallarını içerir.
