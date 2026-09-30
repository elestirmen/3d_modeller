# Production deployment

The Flask app runs in `3d-models-perinet` on the existing `npm-net` Docker network. The model library, `db.json`, generated previews (`thumbnails/`) and the session key (`.secret_key`) stay in this checkout and survive image rebuilds. The container runs as uid/gid `1000` so uploaded files belong to the host user.

```sh
docker compose -f deploy/docker-compose.yml up -d --build
```

Set or change the admin password (stored only as a hash in `db.json`):

```sh
docker exec -it 3d-models-perinet python app.py set-admin-password
```

Nginx Proxy Manager reads `deploy/nginx/3d-models.perinet.org.conf` from its custom HTTP configuration. Uploads are sent in 8 MB chunks, which fits both Cloudflare's 100 MB request limit and Nginx Proxy Manager's global `client_max_body_size`. The Cloudflare record is a proxied CNAME to `urgup.keenetic.link`, the existing Keenetic dynamic DNS name, so DNS follows the home connection when its address changes.

The origin certificate is issued with a Cloudflare DNS challenge and stored in Nginx Proxy Manager's Let's Encrypt volume. The user-level `3d-models-cert-renew.timer` renews it weekly using the local `~/.config/cloudflare/token.env`; the token is not stored in this repository.
