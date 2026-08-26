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
    """ntfy에 JSON으로 보낸다.

    헤더 방식(Title: ...)을 쓰지 않는 이유:
      HTTP 헤더는 latin-1만 담을 수 있어서 한글 제목을 그대로 못 넣는다.
      퍼센트 인코딩해서 넣었더니 폰에 '%EC%9A%94...'로 그대로 떴다(2026-08-26 실제로 겪음).
      ntfy는 JSON 본문 발행도 받는다. 그쪽은 UTF-8이 그대로 통한다.

    priority 5(최대)를 쓰는 이유:
      문의는 한 달에 몇 건 안 온다. 대신 하나를 놓치면 그게 곧 손해다.
      드물고 값진 알림이니 확실히 눈에 띄게 보낸다.
    """
    if not 주제:
        return False, "주제가 비어 있음"
    꾸러미 = {
        "topic": 주제,
        "title": 제목,
        "message": 본문,
        "priority": 5,
        "tags": ["envelope"],
    }
    if 링크:
        꾸러미["click"] = urllib.parse.quote(링크, safe=":/?=&#")
    요청 = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(꾸러미, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    try:
        with urllib.request.urlopen(요청, timeout=8) as r:
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
