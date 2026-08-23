#!/bin/bash
# ============================================================================
# 요양지도 — 서버 설치 스크립트
#
# Vultr 시작 스크립트(yoyangjido-bootstrap)가 GitHub에서 이 파일을 받아 실행합니다.
# 서버를 재부팅할 때마다 다시 실행되므로, 몇 번을 돌려도 같은 결과가 나오도록
# (idempotent) 작성했습니다.
# ============================================================================
set -uxo pipefail

GITHUB_REPO="https://github.com/mingoolee-dev/yoyangjido.git"
DOMAIN="yoyangjido.com"
APP_DIR="/opt/yoyangjido"
XLSX="data/장기요양기관_시설별현황.xlsx"
REGION="군산"
LOGKEY="setup-8f3a91c40b"   # 설치 로그 확인용 임시 경로. 확인 끝나면 지운다.

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git curl ca-certificates \
                   debian-keyring debian-archive-keyring apt-transport-https ufw

# ── 방화벽: 웹과 SSH만 연다 ───────────────────────────────────────────
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ── 앱 내려받기 (이미 있으면 최신으로 맞춘다) ─────────────────────────
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --depth 1 origin main
  git -C "$APP_DIR" reset --hard origin/main
else
  rm -rf "$APP_DIR"
  git clone --depth 1 -b main "$GITHUB_REPO" "$APP_DIR"
fi
cd "$APP_DIR"

[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 시설 DB 만들기
if [ -f "$XLSX" ]; then
  .venv/bin/python build_db.py "$XLSX" "$REGION"
fi

# ── 앱을 서비스로 등록 ────────────────────────────────────────────────
cat >/etc/systemd/system/yoyangjido.service <<'UNIT'
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
UNIT

# ── 2분마다 새 코드를 받아 반영 (SSH 없이 배포하기 위한 장치) ─────────
cat >/usr/local/bin/yoyangjido-update <<'UPD'
#!/bin/bash
cd /opt/yoyangjido || exit 0
BEFORE=$(git rev-parse HEAD)
git fetch --quiet --depth 1 origin main || exit 0
git reset --hard --quiet origin/main
AFTER=$(git rev-parse HEAD)
[ "$BEFORE" = "$AFTER" ] && exit 0
.venv/bin/pip install -q -r requirements.txt
[ -f "data/장기요양기관_시설별현황.xlsx" ] && \
  .venv/bin/python build_db.py "data/장기요양기관_시설별현황.xlsx" 군산
systemctl restart yoyangjido
UPD
chmod +x /usr/local/bin/yoyangjido-update

cat >/etc/systemd/system/yoyangjido-update.service <<'UNIT'
[Unit]
Description=요양지도 코드 갱신
[Service]
Type=oneshot
ExecStart=/usr/local/bin/yoyangjido-update
UNIT

cat >/etc/systemd/system/yoyangjido-update.timer <<'UNIT'
[Unit]
Description=요양지도 코드 갱신 타이머
[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
UNIT

# ── Caddy: HTTPS 인증서를 알아서 받고 갱신합니다 ──────────────────────
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
fi

mkdir -p /var/log/caddy /var/www/diag
cat >/etc/caddy/Caddyfile <<CADDY
${DOMAIN}, www.${DOMAIN} {
    encode zstd gzip
    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }
    handle_path /${LOGKEY}/* {
        root * /var/www/diag
        file_server browse
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
    log {
        output file /var/log/caddy/access.log
    }
}
CADDY

# ── 매일 새벽 DB 백업 ─────────────────────────────────────────────────
mkdir -p /var/backups/yoyangjido
cat >/etc/cron.daily/yoyangjido-backup <<'BK'
#!/bin/bash
D=$(date +%Y%m%d)
cp /opt/yoyangjido/yoyangjido.db /var/backups/yoyangjido/db-$D.sqlite 2>/dev/null || true
find /var/backups/yoyangjido -name 'db-*.sqlite' -mtime +30 -delete
BK
chmod +x /etc/cron.daily/yoyangjido-backup

# ── 켜고 다시 읽히기 (enable --now 만으로는 설정이 갱신되지 않는다) ───
systemctl daemon-reload
systemctl enable yoyangjido yoyangjido-update.timer caddy
systemctl restart yoyangjido
systemctl restart yoyangjido-update.timer
caddy validate --config /etc/caddy/Caddyfile && systemctl restart caddy

# ── 설치 결과를 웹에서 확인할 수 있게 남긴다 (확인 후 제거) ───────────
sleep 4
{
  echo "설치 종료 시각: $(date -Is)"
  echo
  echo "== 서비스 상태 =="
  systemctl is-active yoyangjido caddy yoyangjido-update.timer
  echo
  echo "== 앱 응답 =="
  curl -s -o /dev/null -w "127.0.0.1:8000/healthz -> %{http_code}\n" http://127.0.0.1:8000/healthz
  echo
  echo "== 시설 DB =="
  ls -l "$APP_DIR/yoyangjido.db" 2>&1
  echo
  echo "== 앱 로그 (마지막 40줄) =="
  tail -n 40 /var/log/yoyangjido.log 2>&1
  echo
  echo "== 설치 로그 (마지막 60줄) =="
  tail -n 60 /var/log/yoyangjido-bootstrap.log 2>&1
} > /var/www/diag/status.txt 2>&1
chmod 644 /var/www/diag/status.txt

echo "요양지도 설치 완료 $(date -Is)" >> /var/log/yoyangjido-setup.log
