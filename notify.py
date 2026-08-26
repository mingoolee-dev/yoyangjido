"""문의가 들어온 것을 형님 휴대폰으로 즉시 알린다.

왜 필요한가:
  양식으로 문의를 받아도 우리가 그걸 늦게 보면 소용이 없다.
  업체 입장에서 이틀 뒤 답장은 거절과 같다.
  "하루 안에 답 드립니다"라고 적어놨으면 그 약속을 지킬 수단이 있어야 한다.

무엇을 보내고 무엇을 안 보내는가:
  보내는 것 — "새 문의 1건. 관리 화면에서 보세요."
  안 보내는 것 — 업체명·전화번호 같은 상세 내용.
  알림 통로는 우리가 완전히 통제하지 못한다(공개 주제, 외부 서버).
  남의 연락처를 그런 통로에 흘리지 않는다. 상세는 관리 화면에서만 본다.

채널:
  ntfy   — 가입도 비밀번호도 없다. 앱에서 주제 이름만 맞추면 폰으로 푸시가 온다.
  telegram — 텔레그램 봇. 토큰과 대화방 번호가 필요하다.
  없음    — 알림을 끈다. 양식과 저장은 그대로 돌아간다.
"""
import json
import urllib.parse
import urllib.request


def _보내기_ntfy(주제: str, 제목: str, 본문: str, 링크: str = "") -> tuple[bool, str]:
    if not 주제:
        return False, "주제가 비어 있음"
    머리 = {
        "Title": urllib.parse.quote(제목),   # 한글 제목은 인코딩해야 통과한다
        "Priority": "high",
        "Tags": "envelope",
    }
    if 링크:
        # HTTP 헤더는 latin-1만 담을 수 있다. 한글이 든 주소는 미리 인코딩한다.
        머리["Click"] = urllib.parse.quote(링크, safe=":/?=&#")
    요청 = urllib.request.Request(
        f"https://ntfy.sh/{urllib.parse.quote(주제)}",
        data=본문.encode("utf-8"), headers=머리, method="POST")
    try:
        with urllib.request.urlopen(요청, timeout=6) as r:
            return (200 <= r.status < 300), f"HTTP {r.status}"
    except Exception as e:
        return False, str(e)[:120]


def _보내기_telegram(토큰: str, 방: str, 제목: str, 본문: str) -> tuple[bool, str]:
    if not (토큰 and 방):
        return False, "토큰이나 대화방 번호가 비어 있음"
    자료 = urllib.parse.urlencode({
        "chat_id": 방, "text": f"{제목}\n{본문}"}).encode()
    요청 = urllib.request.Request(
        f"https://api.telegram.org/bot{토큰}/sendMessage", data=자료, method="POST")
    try:
        with urllib.request.urlopen(요청, timeout=6) as r:
            답 = json.loads(r.read().decode())
            return bool(답.get("ok")), "ok" if 답.get("ok") else str(답)[:120]
    except Exception as e:
        return False, str(e)[:120]


def 알림(설정: dict, 제목: str, 본문: str, 링크: str = "") -> tuple[bool, str]:
    """설정에 적힌 채널로 보낸다. 실패해도 예외를 밖으로 내보내지 않는다.
    알림이 실패했다고 해서 문의 접수 자체가 실패하면 안 된다."""
    채널 = (설정.get("채널") or "없음").strip()
    if 채널 == "ntfy":
        return _보내기_ntfy(설정.get("주제", ""), 제목, 본문, 링크)
    if 채널 == "telegram":
        return _보내기_telegram(설정.get("토큰", ""), 설정.get("방", ""), 제목, 본문)
    return False, "알림 채널이 꺼져 있음"
