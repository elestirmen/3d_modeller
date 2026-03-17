# 3D Model Yöneticisi

Yerel `3d models/` klasörünü tarayan, modelleri kataloglayan ve web arayüzü üzerinden filtreleme, etiketleme, favorileme ve STL önizleme sağlayan küçük bir Flask uygulaması.

## Özellikler

- `3d models/` klasörünü tarayıp proje veya tekil dosya olarak kataloglar.
- Dosya ve klasör isimlerinden otomatik etiket önerileri üretir.
- İsim, etiket, format ve favori durumuna göre filtreleme yapar.
- Model bazlı not, favori ve yazdırıldı durumu saklar.
- STL dosyaları için Three.js tabanlı önizleme ve thumbnail üretir.

## Çalıştırma

```bash
pip install -r requirements.txt
python app.py
```

Varsayılan adres `http://localhost:5000` olur.

İlk açılışta katalog taranır. Dosya sisteminde değişiklik yaptıktan sonra arayüzdeki `Yeniden Tara` düğmesini kullanın.

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

- `GET /api/models`: Model listesi. `q`, `tag`, `format`, `sort`, `fav` parametrelerini destekler.
- `POST /api/models/<id>/tags`: Etiketleri günceller.
- `POST /api/models/<id>/favorite`: Favori durumunu değiştirir.
- `POST /api/models/<id>/note`: Notu günceller.
- `POST /api/models/<id>/printed`: Yazdırıldı durumunu değiştirir.
- `GET /api/tags`: Kullanılan etiketleri ve sayılarını döner.
- `POST /api/scan`: Klasörü yeniden tarar.
- `GET /api/stats`: Özet istatistikleri döner.
- `GET /api/file/<path>`: Desteklenen model dosyalarını servis eder.

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
