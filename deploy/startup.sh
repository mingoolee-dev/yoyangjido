#!/bin/bash
# ============================================================================
# 요양지도 — Vultr 서버 시작 스크립트 (Startup Script)
#
# 사용법: Vultr에서 인스턴스를 만들 때 [Startup Script] 칸에 이 내용을 붙여넣습니다.
#        서버가 처음 켜질 때 아래 내용이 자동으로 실행됩니다. SSH 접속이 필요 없습니다.
#
# 아래 GITHUB_REPO 한 줄만 본인 저장소 주소로 바꾸면 됩니다.
# ============================================================================
set -euxo pipefail

GITHUB_REPO="https://github.com/mingoolee-dev/yoyangjido.git"
DOMAIN="yoyangjido.com"
APP_DIR="/opt/yoyangjido"

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates \
                   debian-keyring debian-archive-keyring apt-transport-https ufw

# ── 방화벽: 웹만 열고 나머지는 닫는다 ──────────────────────────────────
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ── 앱 내려받기 ───────────────────────────────────────────────────────
git clone --depth 1 "$GITHUB_REPO" "$APP_DIR"
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 시설 DB 만들기 (원본 xlsx가 저장소에 들어 있어야 합니다)
if [ -f data/장기요양기관_시설별현황.xlsx ]; then
  .venv/bin/python build_db.py data/장기요양기관_시설별현황.xlsx 군산
fi

# ── 앱을 서비스로 등록 ────────────────────────────────────────────────
cat >/etc/systemd/system/yoyangjido.service <<'EOF'
[Unit]
Description=요양지도
After=network.target

[Service]
WorkingDirectory=/opt/yoyangjido
ExecStart=/opt/yoyangjido/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3
StandardOutput=append:/var/log/yoyangjido.log
StandardError=append:/var/log/yoyangjido.log

[Install]
WantedBy=multi-user.target
EOF

# ── 2분마다 새 코드를 받아 반영 (SSH 없이 배포하기 위한 장치) ─────────
cat >/usr/local/bin/yoyangjido-update <<'EOF'
#!/bin/bash
cd /opt/yoyangjido || exit 0
BEFORE=$(git rev-parse HEAD)
git fetch --quiet origin && git reset --hard --quiet origin/HEAD
AFTER=$(git rev-parse HEAD)
[ "$BEFORE" = "$AFTER" ] && exit 0
.venv/bin/pip install -q -r requirements.txt
[ -f data/장기요양기관_시설별현황.xlsx ] && .venv/bin/python build_db.py data/장기요양기관_시설별현황.xlsx 군산
systemctl restart yoyangjido
EOF
chmod +x /usr/local/bin/yoyangjido-update

cat >/etc/systemd/system/yoyangjido-update.service <<'EOF'
[Unit]
Description=요양지도 코드 갱신
[Service]
Type=oneshot
ExecStart=/usr/local/bin/yoyangjido-update
EOF

cat >/etc/systemd/system/yoyangjido-update.timer <<'EOF'
[Unit]
Description=요양지도 코드 갱신 타이머
[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
EOF

# ── Caddy: HTTPS 인증서를 알아서 발급받고 갱신합니다 ──────────────────
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y && apt-get install -y caddy

cat >/etc/caddy/Caddyfile <<EOF
${DOMAIN}, www.${DOMAIN} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }
    log {
        output file /var/log/caddy/access.log
    }
}
EOF

# ── 매일 새벽 DB 백업 (18장: 백업은 복구해봐야 백업이다) ───────────────
mkdir -p /var/backups/yoyangjido
cat >/etc/cron.daily/yoyangjido-backup <<'EOF'
#!/bin/bash
D=$(date +%Y%m%d)
cp /opt/yoyangjido/yoyangjido.db /var/backups/yoyangjido/db-$D.sqlite 2>/dev/null || true
find /var/backups/yoyangjido -name 'db-*.sqlite' -mtime +30 -delete
EOF
chmod +x /etc/cron.daily/yoyangjido-backup

systemctl daemon-reload
systemctl enable --now yoyangjido
systemctl enable --now yoyangjido-update.timer
systemctl enable --now caddy

echo "요양지도 설치 완료 $(date)" >> /var/log/yoyangjido-setup.log
