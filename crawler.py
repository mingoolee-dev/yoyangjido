"""검색·AI 크롤러가 실제로 다녀갔는지 기록한다.

왜 필요한가:
  "네이버에 등록했다", "구글에 제출했다"는 것은 제출했다는 뜻이지
  수집됐다는 뜻이 아니다. 신규 도메인은 3~6주 검수를 거친다.
  그 사이에 우리가 확인할 수 있는 유일한 사실은
  "그 크롤러의 요청이 우리 서버에 실제로 도착했는가" 하나다.

  제출 화면의 초록색 표시는 증거가 아니다. 접속 기록이 증거다.

기록하는 것: 크롤러 이름, 처음/마지막 방문 시각, 누적 횟수, 마지막 경로.
기록하지 않는 것: 사람 방문자. IP도 남기지 않는다.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = Path(__file__).parent / "crawler.db"
KST = timezone(timedelta(hours=9))

# user-agent에 이 문자열이 들어 있으면 그 크롤러로 본다. 위에서부터 먼저 맞는 것.
크롤러 = [
    ("네이버 Yeti",        "yeti"),
    ("구글 Googlebot",     "googlebot"),
    ("구글 AI(Extended)",  "google-extended"),
    ("구글 인스펙션",       "google-inspectiontool"),
    ("빙 Bingbot",         "bingbot"),
    ("다음 Daum",          "daum"),
    ("ChatGPT 검색",       "oai-searchbot"),
    ("ChatGPT 학습",       "gptbot"),
    ("ChatGPT 사용자요청",  "chatgpt-user"),
    ("Claude",             "claudebot"),
    ("Claude 사용자요청",   "claude-user"),
    ("Perplexity",         "perplexitybot"),
    ("Perplexity 사용자요청","perplexity-user"),
    ("Apple",              "applebot"),
    ("Bytespider",         "bytespider"),
    ("Amazon",             "amazonbot"),
    ("Meta",               "meta-externalagent"),
]


def _con():
    con = sqlite3.connect(DB, timeout=3)
    con.row_factory = sqlite3.Row
    return con


def 준비():
    with _con() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS 방문(
                이름 TEXT PRIMARY KEY,
                처음 TEXT, 마지막 TEXT, 횟수 INTEGER, 마지막경로 TEXT
            )""")


def 판별(ua: str) -> str | None:
    u = (ua or "").lower()
    for 이름, 조각 in 크롤러:
        if 조각 in u:
            return 이름
    return None


def 기록(ua: str, 경로: str) -> None:
    """크롤러면 남기고, 사람이면 아무것도 하지 않는다.
    기록이 실패해도 페이지는 정상적으로 나가야 한다."""
    이름 = 판별(ua)
    if not 이름:
        return
    지금 = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    try:
        with _con() as con:
            con.execute("""
                INSERT INTO 방문(이름, 처음, 마지막, 횟수, 마지막경로)
                VALUES(?,?,?,1,?)
                ON CONFLICT(이름) DO UPDATE SET
                    마지막 = excluded.마지막,
                    횟수 = 횟수 + 1,
                    마지막경로 = excluded.마지막경로
            """, (이름, 지금, 지금, 경로[:200]))
    except Exception:
        pass


def 목록() -> list[dict]:
    try:
        with _con() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM 방문 ORDER BY 마지막 DESC")]
    except Exception:
        return []


# ── 사람 방문자 수 ──────────────────────────────────────────────────────
# 왜 필요한가:
#   광고주에게 "월 방문자 ○○○명이면 그때부터 받겠습니다"라고 약속하려면
#   그 숫자를 우리가 실제로 셀 수 있어야 한다.
#   셀 수 없는 약속은 하지 않는다.
#
# 무엇을 세는가: 크롤러가 아닌 요청의 페이지 조회 수를, 달 단위로.
# 무엇을 세지 않는가: IP도 쿠키도 남기지 않는다. 개인을 식별하지 않는다.
#   그래서 이 숫자는 '순 방문자'가 아니라 '페이지 조회'다. 광고주에게도 그렇게 말한다.

def 방문_준비():
    with _con() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS 조회(
                달 TEXT, 경로 TEXT, 횟수 INTEGER,
                PRIMARY KEY (달, 경로)
            )""")


def 방문_기록(ua: str, 경로: str) -> None:
    """사람 요청만 센다. 크롤러·정적파일·진단경로는 빼고."""
    if 판별(ua):
        return
    if 경로.startswith(("/static/", "/setup-")) or 경로 in ("/healthz", "/favicon.ico",
                                                          "/robots.txt", "/sitemap.xml"):
        return
    달 = datetime.now(KST).strftime("%Y-%m")
    try:
        with _con() as con:
            con.execute("""
                INSERT INTO 조회(달, 경로, 횟수) VALUES(?,?,1)
                ON CONFLICT(달, 경로) DO UPDATE SET 횟수 = 횟수 + 1
            """, (달, 경로[:200]))
    except Exception:
        pass


def 방문_요약(달수: int = 6) -> list[dict]:
    """달별 합계와 그 달의 상위 경로."""
    try:
        with _con() as con:
            달목록 = [r["달"] for r in con.execute(
                "SELECT 달 FROM 조회 GROUP BY 달 ORDER BY 달 DESC LIMIT ?", (달수,))]
            결과 = []
            for m in 달목록:
                합 = con.execute("SELECT SUM(횟수) s FROM 조회 WHERE 달=?", (m,)).fetchone()["s"] or 0
                상위 = [(r["경로"], r["횟수"]) for r in con.execute(
                    "SELECT 경로, 횟수 FROM 조회 WHERE 달=? ORDER BY 횟수 DESC LIMIT 8", (m,))]
                결과.append({"달": m, "합계": 합, "상위": 상위})
            return 결과
    except Exception:
        return []
