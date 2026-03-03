# 🧊 3D Model Yöneticisi

Dağınık 3D model dosyalarını tarayan, kataloglayan ve yöneten web uygulaması. STL, 3MF, OBJ, GLTF, GLB, FBX ve PLY formatlarını kataloglar, filtreler ve listeler. Etkileşimli 3D önizleme şu an STL dosyaları için sunulur.

## Özellikler

- **Tarama kataloğu** — `3d models` klasöründeki tüm modelleri ilk açılışta kataloglar, `Yeniden Tara` ile günceller
- **Akıllı etiketleme** — Dosya/klasör adından otomatik kategori önerisi
- **Arama ve filtreleme** — İsim, etiket veya format ile arama
- **Favoriler** — Sık kullandığınız modelleri işaretleyin
- **Notlar** — Her model için özel not ekleyin
- **Yazdırıldı takibi** — Hangi modellerin baskısını aldığınızı kaydedin

## Kurulum

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Uygulamayı başlat
python app.py
```

Tarayıcıda **http://localhost:5000** adresine gidin.

İlk açılışta klasör taranır. Dosya sisteminde sonradan yaptığınız değişiklikleri arayüze yansıtmak için **Yeniden Tara** düğmesini kullanın.

## Klasör yapısı

```
3d_modeller/
├── app.py              # Flask backend
├── db.json             # Kullanıcı verileri (etiketler, favoriler, notlar)
├── requirements.txt
├── 3d models/          # 3D model dosyalarınızı buraya koyun
│   ├── proje-1/
│   │   ├── model.stl
│   │   └── ...
│   └── model.stl
├── static/
└── templates/
```

## Desteklenen formatlar

| Format | Uzantı |
|--------|--------|
| STL | `.stl` |
| 3MF | `.3mf` |
| OBJ | `.obj` |
| glTF | `.gltf`, `.glb` |
| FBX | `.fbx` |
| PLY | `.ply` |

## API

| Endpoint | Açıklama |
|---------|----------|
| `GET /api/models` | Model listesi (q, tag, format, sort, fav parametreleri) |
| `POST /api/models/<id>/tags` | Etiket güncelle |
| `POST /api/models/<id>/favorite` | Favori toggle |
| `POST /api/models/<id>/note` | Not güncelle |
| `POST /api/models/<id>/printed` | Yazdırıldı toggle |
| `GET /api/tags` | Tüm etiketler |
| `POST /api/scan` | Yeniden tara |
| `GET /api/stats` | İstatistikler |

## Test

```bash
python -m unittest -v
```

## Gereksinimler

- Python 3.8+
- Flask 3.0+
