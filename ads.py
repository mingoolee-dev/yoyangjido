"""제휴 배너 자리 — 우리 수익의 본체.

왜 이 파일이 필요한가:
  우리 수익은 클릭 단가(CPC)나 애드센스가 아니다. 업체가 '자리'를 사는 정액 모델이다.
  그래서 매출은 이렇게 계산된다.

      매출 = 자리 수 × 자리당 월 단가 × 판매율

  방문자 수가 곱해지지 않는다. 방문자 수는 '자리를 팔 수 있느냐'를 가르는
  문턱일 뿐, 매출을 곱하는 값이 아니다. 이 구분이 이 사업의 전부다.

  따라서 우리가 늘려야 할 것은 방문자가 아니라 '팔 수 있는 자리'다.
  자리는 두 축으로 늘어난다.
      주제축 — 간병비 글에는 간병업체, 상속 글에는 세무사
      지역축 — 군산 목록에는 군산 요양원, 익산 목록에는 익산 요양원
  둘은 곱해진다. 지역 229개 × 유형 2개 × 자리 3개 = 1,374자리.

빈 자리를 비워두지 않는 이유:
  광고주가 없는 자리에는 '이 자리 문의' 안내를 넣는다.
  전화 영업으로 300곳을 뚫는 건 혼자서 불가능하다.
  빈 자리가 24시간 대신 영업하게 만드는 것이 유일하게 확장되는 방법이다.

절대 하지 않는 것 (19장 금지 목록):
  - 돈 받고 시설 목록 순서를 바꾸지 않는다. 배너는 목록 '밖'에만 둔다.
  - 배너에 반드시 '광고'라고 적는다. 정보인 척하지 않는다.
  - 유료 링크는 rel="nofollow sponsored"를 단다. (구글 정책)
  - 입소 성사 수수료는 받지 않는다. 자리값만 받는다.
"""
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = Path(__file__).parent / "ads.db"
KST = timezone(timedelta(hours=9))

# ── 유료 판매 개시 조건 ────────────────────────────────────────────────
# 이 숫자를 넘기 전에는 자리를 무료로 깔아준다.
# 근거: 셀 수 없는 약속은 하지 않는다. 실제로 센 조회 수만 광고주에게 말한다.
유료개시_월조회 = 5_000

# ── 자리 목록 ─────────────────────────────────────────────────────────
# 키 = "페이지:대상:번호". 템플릿에서 이 키로 부른다.
# 월단가 = 유료 개시 후 정가(원). 지금은 전부 무료.
자리정의 = [
    # 주제축 ─ 전국 대상
    ("간병비:간병업체:1", "간병비 글", "간병인 소개소·간병 업체", 200_000),
    ("간병비:간병업체:2", "간병비 글", "간병인 소개소·간병 업체", 200_000),
    ("간병비:간병업체:3", "간병비 글", "간병인 소개소·간병 업체", 200_000),
    ("요양병원비용:요양병원:1", "요양병원 비용 글", "요양병원", 300_000),
    ("요양병원비용:요양병원:2", "요양병원 비용 글", "요양병원", 300_000),
    ("요양병원비용:요양병원:3", "요양병원 비용 글", "요양병원", 300_000),
    ("계산기:요양원:1", "본인부담금 계산기", "요양원", 300_000),
    ("계산기:요양원:2", "본인부담금 계산기", "요양원", 300_000),
    ("계산기:복지용구:1", "본인부담금 계산기", "복지용구 업체", 150_000),
    ("차이:요양원:1", "요양원·요양병원 차이 글", "요양원·요양병원", 200_000),
    ("차이:요양원:2", "요양원·요양병원 차이 글", "요양원·요양병원", 200_000),
    # 지역축 ─ 군산. 여기서 검증되면 229개 시군구로 그대로 복제한다.
    ("군산:요양원:1", "군산 시설 목록", "군산 지역 요양원", 150_000),
    ("군산:요양원:2", "군산 시설 목록", "군산 지역 요양원", 150_000),
    ("군산요양원:요양원:1", "군산 요양원 목록", "군산 지역 요양원", 150_000),
    ("군산요양원:요양원:2", "군산 요양원 목록", "군산 지역 요양원", 150_000),
    ("군산방문요양:재가:1", "군산 방문요양 목록", "군산 지역 재가센터", 100_000),
    ("군산방문요양:재가:2", "군산 방문요양 목록", "군산 지역 재가센터", 100_000),
]
자리표 = {k: {"키": k, "페이지": p, "대상": t, "월단가": w}
          for k, p, t, w in 자리정의}


def _con():
    con = sqlite3.connect(DB, timeout=3)
    con.row_factory = sqlite3.Row
    return con


def 준비():
    with _con() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS 게재(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                자리키 TEXT NOT NULL,
                업체명 TEXT NOT NULL,
                한줄 TEXT,
                전화 TEXT,
                링크 TEXT,
                시작일 TEXT,
                종료일 TEXT,
                월단가 INTEGER DEFAULT 0,
                상태 TEXT DEFAULT '게재중'
            )""")
        con.execute("""
            CREATE TABLE IF NOT EXISTS 집계(
                게재id INTEGER, 달 TEXT, 노출 INTEGER DEFAULT 0, 클릭 INTEGER DEFAULT 0,
                PRIMARY KEY (게재id, 달)
            )""")


def _오늘():
    return datetime.now(KST).strftime("%Y-%m-%d")


def 자리(키: str):
    """이 자리에 지금 걸린 광고를 돌려준다. 없으면 None.
    없으면 템플릿이 '이 자리 문의' 안내를 대신 띄운다."""
    오늘 = _오늘()
    try:
        with _con() as con:
            r = con.execute("""
                SELECT * FROM 게재
                 WHERE 자리키=? AND 상태='게재중'
                   AND (시작일 IS NULL OR 시작일<=?)
                   AND (종료일 IS NULL OR 종료일>=?)
                 ORDER BY id LIMIT 1
            """, (키, 오늘, 오늘)).fetchone()
            return dict(r) if r else None
    except Exception:
        return None


def 노출(게재id: int) -> None:
    달 = datetime.now(KST).strftime("%Y-%m")
    try:
        with _con() as con:
            con.execute("""
                INSERT INTO 집계(게재id, 달, 노출, 클릭) VALUES(?,?,1,0)
                ON CONFLICT(게재id, 달) DO UPDATE SET 노출 = 노출 + 1
            """, (게재id, 달))
    except Exception:
        pass


def 클릭(게재id: int) -> str | None:
    """클릭을 세고 보낼 주소를 돌려준다."""
    달 = datetime.now(KST).strftime("%Y-%m")
    try:
        with _con() as con:
            con.execute("""
                INSERT INTO 집계(게재id, 달, 노출, 클릭) VALUES(?,?,0,1)
                ON CONFLICT(게재id, 달) DO UPDATE SET 클릭 = 클릭 + 1
            """, (게재id, 달))
            r = con.execute("SELECT 링크 FROM 게재 WHERE id=?", (게재id,)).fetchone()
            return r["링크"] if r else None
    except Exception:
        return None


def 성과(게재id: int, 달: str | None = None) -> dict:
    """광고주에게 보여줄 숫자. 이게 없으면 재계약이 안 된다."""
    달 = 달 or datetime.now(KST).strftime("%Y-%m")
    try:
        with _con() as con:
            r = con.execute("SELECT 노출, 클릭 FROM 집계 WHERE 게재id=? AND 달=?",
                            (게재id, 달)).fetchone()
            return {"노출": r["노출"], "클릭": r["클릭"]} if r else {"노출": 0, "클릭": 0}
    except Exception:
        return {"노출": 0, "클릭": 0}


def 전체현황() -> list[dict]:
    """자리별로 '팔렸는지 / 비었는지 / 이번 달 성과'를 한 줄씩."""
    결과 = []
    달 = datetime.now(KST).strftime("%Y-%m")
    for 키, 정의 in 자리표.items():
        걸린것 = 자리(키)
        행 = dict(정의)
        행["업체"] = 걸린것["업체명"] if 걸린것 else None
        행["성과"] = 성과(걸린것["id"], 달) if 걸린것 else {"노출": 0, "클릭": 0}
        결과.append(행)
    return 결과


def 재고() -> dict:
    """지금 팔 수 있는 자리가 몇 개고, 다 팔면 월 얼마인가."""
    현황 = 전체현황()
    빈자리 = [r for r in 현황 if not r["업체"]]
    return {
        "총자리": len(현황),
        "판매됨": len(현황) - len(빈자리),
        "빈자리": len(빈자리),
        "정가합계": sum(r["월단가"] for r in 현황),
        "미판매액": sum(r["월단가"] for r in 빈자리),
    }
