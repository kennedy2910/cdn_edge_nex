# Reset / Desinstalar tudo (EDGE CDN v11)

Se você quer **zerar** e começar do 0:

```bash
cd edge-cdn-v11
chmod +x scripts/*.sh
./scripts/reset.sh
./scripts/install.sh
```

O `reset.sh` faz:
- `docker compose down -v`
- remove `./data` (cache do nginx + HLS + configs copiados)

Se você estiver sem permissão no Docker:
- rode com sudo: `sudo ./scripts/reset.sh`
- ou coloque seu usuário no grupo docker e reabra a sessão:
  - `sudo usermod -aG docker $USER`
  - logout/login
