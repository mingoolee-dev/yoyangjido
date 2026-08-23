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
# 설치 상태 확인용 비공개 경로.
# 로그 전문은 더 이상 공개하지 않는다. 서비스가 살아 있는지와 배포된 커밋만 적는다.
LOGKEY="setup-8f3a91c40b"

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

# 설치 스크립트 자체가 바뀌었으면 서버 설정까지 다시 맞춘다.
# (SSH를 못 쓰므로, 이것이 서버 설정을 바꾸는 유일한 통로다. 재부팅이 필요 없어진다.)
if ! git diff --quiet "$BEFORE" "$AFTER" -- deploy/startup.sh 2>/dev/null; then
  systemd-run --collect --unit="yoyangjido-setup-$AFTER" \
    /bin/bash /opt/yoyangjido/deploy/startup.sh
  exit 0
fi

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
    handle /${LOGKEY} {
        root * /var/www/diag
        rewrite * /status.txt
        header Content-Type "text/plain; charset=utf-8"
        header X-Robots-Tag "noindex, nofollow"
        file_server
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

# ── 설치 결과 요약 ────────────────────────────────────────────────────
# 로그 전문은 남기지 않는다. 서버 로그를 웹에 공개하면 경로·오류 내용이 그대로 새어나간다.
# 여기 적는 것은 "살아 있는가"와 "어느 커밋이 올라가 있는가" 두 가지뿐이다.
sleep 4
{
  echo "확인 시각      : $(date -Is)"
  echo "배포 커밋      : $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo 확인불가)"
  echo "앱             : $(systemctl is-active yoyangjido)"
  echo "웹서버         : $(systemctl is-active caddy)"
  echo "갱신 타이머    : $(systemctl is-active yoyangjido-update.timer)"
  echo "healthz 응답   : $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz)"
  echo "시설 DB 크기   : $(stat -c %s "$APP_DIR/yoyangjido.db" 2>/dev/null || echo 없음) bytes"
} > /var/www/diag/status.txt 2>&1
chmod 644 /var/www/diag/status.txt

echo "요양지도 설치 완료 $(date -Is)" >> /var/log/yoyangjido-setup.log
