"""요양지도 — 요양·간병 보호자를 위한 중립 정보 인프라"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import ads
import caregiving
import compare
import crawler
import fees
import hospital
import notify
import seo

BASE = Path(__file__).parent
DB = BASE / "yoyangjido.db"
SITE = "요양지도"
DOMAIN = "https://yoyangjido.com"
DATA_기준일 = "2026-06-10"
갱신일 = "2026-08-25"          # 페이지 하단·스키마에 노출. 손볼 때마다 올린다.
DATA_출처 = "국민건강보험공단 장기요양기관 시설별 현황"
DATA_URL = "https://www.data.go.kr/data/15124763/fileData.do"
# 광고 문의 창구. 비워두면 광고안내 페이지가 "준비 중"으로 나간다.
# 공개 페이지에 실릴 값이라 형님 확인 없이 채우지 않는다.
광고문의 = "min9net@naver.com"

네이버_소유확인 = "2c9d401492f180b478c418fc8ea419e927096426"   # 서치어드바이저 · 2026-08-23 등록. 1년마다 갱신 필요

유형순서 = ["요양원", "공동생활가정", "치매전담실", "주야간보호", "단기보호",
            "방문요양", "방문목욕", "방문간호", "복지용구"]
유형설명 = {
    "요양원": "24시간 모시고 생활을 돕는 곳입니다. 의료 처치가 주 목적은 아닙니다.",
    "공동생활가정": "9인 이하 소규모로 가정처럼 모시는 곳입니다.",
    "치매전담실": "치매 어르신만 따로 모시는 전담 공간입니다.",
    "주야간보호": "낮 동안만 모셨다가 저녁에 집으로 모셔다 드립니다. 어르신 유치원이라고도 합니다.",
    "단기보호": "보호자가 며칠 자리를 비울 때 잠시 모시는 곳입니다.",
    "방문요양": "요양보호사가 집으로 찾아와 돌봐드립니다.",
    "방문목욕": "목욕 차량이나 요양보호사가 집으로 와 목욕을 도와드립니다.",
    "방문간호": "간호사가 집으로 찾아와 간호를 해드립니다.",
    "복지용구": "휠체어·침대·기저귀 같은 용품을 급여로 사거나 빌리는 곳입니다.",
}
# 경로형 주소를 갖는 유형. 검색 수요가 확인된 것만 연다.
# (Ahrefs 2026-08-24: 주야간보호·방문목욕·치매전담실은 검색량 0이라 열지 않았다)
경로유형 = {
    "요양원": "요양원",
    "방문요양": "방문요양",
}


여정단계 = ["걱정 시작", "등급 신청", "시설 선택", "모시는 중", "그 이후"]

app = FastAPI(title=SITE, docs_url=None, redoc_url=None)
# 후행 슬래시 자동 리디렉션을 끈다.
#   /시설/전북/군산시/요양원/   → 유형 페이지
#   /시설/전북/군산시/은혜요양원-0462 → 시설 상세
# 자동 리디렉션이 켜져 있으면 앞의 것이 뒤의 규칙으로 빨려 들어간다(2026-08-24 실제로 겪음).
app.router.redirect_slashes = False
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

crawler.준비()
crawler.방문_준비()
ads.준비()
ads.문의_준비()


@app.middleware("http")
async def 접속_기록(request: Request, call_next):
    """크롤러가 왔는지, 그리고 사람이 몇 번 봤는지를 센다.
    개인을 식별하지 않는다. IP도 쿠키도 남기지 않는다."""
    ua = request.headers.get("user-agent", "")
    crawler.기록(ua, request.url.path)
    crawler.방문_기록(ua, request.url.path)
    return await call_next(request)


tpl = Jinja2Templates(directory=BASE / "templates")
tpl.env.filters["won"] = lambda v: f"{int(v):,}"
tpl.env.filters["jsonld"] = lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def 절대주소(경로: str) -> str:
    """한글 경로를 퍼센트 인코딩한 절대 주소.
    사이트맵 규격은 URL을 RFC-3986으로 이스케이프하도록 요구한다.
    한글을 그대로 넣으면 구글이 사이트맵을 읽지 못한다(2026-08-23 실제로 겪음)."""
    return DOMAIN + quote(경로, safe="/")


def _조사(말: str, 쌍: str = "을/를") -> str:
    """받침 유무에 따라 을/를, 이/가, 은/는을 고른다.
    '간병 업체을 찾습니다' 같은 실수를 코드가 막는다."""
    있, 없 = 쌍.split("/")
    if not 말:
        return 없
    끝 = 말.strip()[-1]
    if not ("가" <= 끝 <= "힣"):
        return 없
    받침 = (ord(끝) - 0xAC00) % 28
    return 있 if 받침 else 없


tpl.env.filters["조사"] = _조사


def ctx(**kw):
    base = {
        "SITE": SITE, "DOMAIN": DOMAIN, "여정단계": 여정단계,
        "DATA_기준일": DATA_기준일, "DATA_출처": DATA_출처, "DATA_URL": DATA_URL,
        "갱신일": 갱신일, "네이버_소유확인": 네이버_소유확인, "절대주소": 절대주소,
        # 기본은 색인 금지. 켤 페이지에서만 명시적으로 뒤집는다.
        "색인": False, "canonical": None, "스키마": [], "경로유형": 경로유형,
        # 배너 자리. 광고가 걸려 있으면 노출을 세고, 없으면 '이 자리 문의'가 뜬다.
        "광고자리": _광고자리, "광고정의": ads.자리표, "광고문의": 광고문의,
    }
    base.update(kw)
    return base


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    con = db()
    총계 = con.execute("SELECT COUNT(*) c FROM facility").fetchone()["c"]
    유형별 = {r["type"]: r["c"] for r in con.execute(
        "SELECT type, COUNT(*) c FROM facility_type GROUP BY type")}
    con.close()
    순 = [(t, 유형별[t]) for t in 유형순서 if t in 유형별]
    return tpl.TemplateResponse(request, "index.html", ctx(
        총계=총계, 유형별=순, 색인=True, canonical="/",
        스키마=[seo.조직_스키마(), seo.웹사이트_스키마()]))


@app.get("/계산기/요양원-본인부담금", response_class=HTMLResponse)
def calc(request: Request,
         등급: str = Query("", alias="등급"),
         일수: int = Query(30, ge=1, le=31),
         비급여: int = Query(0, ge=0, le=5_000_000)):
    결과 = None
    if 등급 in fees.노인요양시설:
        결과 = fees.요양원_월비용(등급, 일수, 비급여)

    표 = fees.노인요양시설
    qa = [
        ("2026년 요양원 한 달 본인부담금은 얼마인가요?",
         f"장기요양 1등급은 하루 {표['1']['본인부담']:,}원으로 30일 기준 {표['1']['본인부담']*30:,}원, "
         f"2등급은 {표['2']['본인부담']*30:,}원, 3·4·5등급은 {표['3']['본인부담']*30:,}원입니다. "
         "급여비용의 20%가 본인부담이며 나머지 80%는 공단이 냅니다. "
         "여기에 식재료비 등 비급여가 별도로 붙습니다. "
         "출처: 보건복지부 2026년도 장기요양 급여유형별 수가(2025-11-04 의결)."),
        ("요양원 비용에 식비가 포함되나요?",
         "포함되지 않습니다. 식재료비·상급침실 이용료·이미용비는 급여 대상이 아니라 전액 본인 부담이고 "
         "시설마다 금액이 다릅니다. 상담할 때 시설에 직접 확인해야 합니다."),
        ("장기요양등급이 있으면 요양병원 비용도 지원되나요?",
         "지원되지 않습니다. 장기요양급여는 재가급여·시설급여·특별현금급여 세 가지뿐이며 "
         "요양병원 입원비는 여기에 포함되지 않습니다. 요양병원은 의료기관이라 건강보험이 적용되고 "
         "간병비가 따로 듭니다. 근거: 노인장기요양보험법 제23조~제26조."),
        ("기초생활수급자는 요양원 비용이 얼마인가요?",
         "본인부담금 감경 제도가 있습니다. 의료급여 수급권자는 본인일부부담금의 60%를, "
         "소득·재산이 기준 이하인 분은 40% 또는 60%를 감경받습니다. "
         "1등급이면 한 달 558,420원이 223,368원까지 내려갑니다. "
         "대상이 되는 소득·재산 기준은 해마다 새로 고시되므로 직접 계산하실 필요 없이 "
         "국민건강보험공단 1577-1000에 전화하시면 대상인지 바로 알려줍니다. "
         "출처: 국민건강보험공단 장기요양보험료 및 본인부담금 안내."),
    ]
    return tpl.TemplateResponse(request, "calc.html", ctx(
        결과=결과, 등급=등급, 일수=일수, 비급여=비급여, 표=표, fees=fees, qa=qa,
        색인=True, canonical="/계산기/요양원-본인부담금",
        스키마=[seo.질문답변_스키마(qa),
              seo.계산기_스키마(fees.기준일, fees.출처URL),
              seo.이동경로_스키마([("요양지도", "/"), ("요양원 본인부담금 계산", "/계산기/요양원-본인부담금")])]))


@app.get("/시설/전북/군산시/", response_class=HTMLResponse)
def region(request: Request, 유형: str = Query("", alias="유형")):
    con = db()
    유형별 = {r["type"]: r["c"] for r in con.execute(
        "SELECT type, COUNT(*) c FROM facility_type GROUP BY type")}
    if 유형 in 유형별:
        rows = con.execute("""
            SELECT f.*, t.capacity FROM facility f
            JOIN facility_type t ON t.code = f.code AND t.type = ?
            ORDER BY t.capacity DESC, f.name""", (유형,)).fetchall()
    else:
        유형 = ""
        rows = con.execute(
            "SELECT *, 대표정원 AS capacity FROM facility ORDER BY 대표정원 DESC, name").fetchall()
    con.close()
    순 = [(t, 유형별[t]) for t in 유형순서 if t in 유형별]
    총계 = sum(유형별.values())

    # 필터를 건 주소는 원본과 내용이 겹친다. 색인하지 않고 원본을 가리킨다.
    필터중 = bool(유형)
    스키마 = []
    if not 필터중:
        스키마 = [seo.데이터셋_스키마(DATA_기준일, DATA_URL, len(rows)),
                seo.이동경로_스키마([("요양지도", "/"), ("전북특별자치도", ""),
                                ("군산시 요양시설", "/시설/전북/군산시/")])]
    return tpl.TemplateResponse(request, "region.html", ctx(
        rows=rows, 유형=유형, 유형별=순, 유형설명=유형설명, 총계=총계, seo=seo,
        색인=not 필터중, canonical="/시설/전북/군산시/", 스키마=스키마))


def _유형_비용(유형):
    """유형마다 비용 구조가 다르다. 같은 표를 돌려쓰지 않는다."""
    if 유형 == "요양원":
        표 = fees.노인요양시설
        return {
            "요약": (f"2026년 기준 한 달 본인부담금은 1등급 <strong>{표['1']['본인부담']*30:,}원</strong>, "
                    f"2등급 {표['2']['본인부담']*30:,}원, 3·4·5등급 {표['3']['본인부담']*30:,}원입니다(30일 기준). "
                    "여기에 식재료비 등 비급여가 따로 붙습니다."),
            "설명": (f"급여비용의 <strong>{int(fees.시설급여_본인부담률*100)}%</strong>가 본인부담이고 "
                    "나머지는 공단이 냅니다. 등급이 정해지면 <strong>전국 어디나 하루 금액이 같습니다.</strong>"),
            "표": {"제목": "2026년 노인요양시설 하루·한 달 금액",
                   "머리": ["등급", "수가(하루)", "본인부담(하루)", "본인부담(30일)"],
                   "행": [[f"{g}등급", f"{표[g]['수가']:,}원", f"{표[g]['본인부담']:,}원",
                          f"{표[g]['본인부담']*30:,}원"] for g in ("1","2","3","4","5")]},
            "주의": ("이 표에 <strong>식재료비·상급침실료·이미용비는 들어 있지 않습니다.</strong> "
                    "급여 대상이 아니라 전액 본인 부담이고 시설마다 다릅니다. "
                    "상담하실 때 “비급여가 한 달에 얼마입니까”를 따로 물어보세요."),
            "다음글": {"제목": "요양원과 요양병원이 헷갈리신다면",
                      "설명": "이름은 비슷한데 제도도 비용 구조도 완전히 다릅니다.",
                      "링크": "/글/요양원-요양병원-차이", "버튼": "차이 보기"},
        }
    if 유형 == "방문요양":
        구간 = sorted(fees.방문요양.items())
        return {
            "요약": (f"요양보호사가 집으로 찾아옵니다. 2026년 기준 "
                    f"{구간[0][0]}분 방문이 본인부담 <strong>{구간[0][1][1]:,}원</strong>, "
                    f"{구간[-1][0]}분 방문이 {구간[-1][1][1]:,}원입니다."),
            "설명": (f"재가급여는 급여비용의 <strong>{int(fees.재가급여_본인부담률*100)}%</strong>가 본인부담입니다. "
                    "요양원(20%)보다 낮습니다. 다만 <strong>등급별 월 한도액</strong>이 있어서 "
                    "그 안에서만 쓸 수 있습니다 — "
                    f"1등급 {fees.재가_월한도액['1']:,}원, 3등급 {fees.재가_월한도액['3']:,}원, "
                    f"5등급 {fees.재가_월한도액['5']:,}원."),
            "표": {"제목": "2026년 방문요양 1회 방문 금액",
                   "머리": ["방문 시간", "수가", "본인부담(15%)"],
                   "행": [[f"{분}분", f"{v[0]:,}원", f"{v[1]:,}원"] for 분, v in 구간]},
            "주의": ("월 한도액을 넘겨 쓰시면 <strong>넘긴 부분은 전액 본인 부담</strong>입니다. "
                    "한 달에 몇 번 오시게 할지는 한도액을 보고 정하셔야 합니다."),
            "다음글": {"제목": "시설에 모시는 쪽도 알아보고 계시다면",
                      "설명": "요양원은 24시간 모시는 곳이고 계산 방식이 다릅니다.",
                      "링크": "/시설/전북/군산시/요양원/", "버튼": "군산시 요양원 보기"},
        }
    return {}


@app.get("/시설/전북/군산시", response_class=HTMLResponse)
def region_no_slash():
    return RedirectResponse("/시설/전북/군산시/", status_code=301)


@app.get("/시설/전북/군산시/{kind}/", response_class=HTMLResponse)
def 유형페이지(request: Request, kind: str):
    # 경로 파라미터 이름은 반드시 ASCII여야 한다.
    # Starlette는 {유형} 같은 한글 이름을 파라미터로 인식하지 못하고
    # 문자 그대로의 경로로 취급한다(2026-08-24 실제로 겪음).
    유형 = kind
    if 유형 not in 경로유형:
        con = db()
        있음 = con.execute("SELECT 1 FROM facility_type WHERE type = ? LIMIT 1", (유형,)).fetchone()
        con.close()
        # 검색 수요가 없어 페이지를 열지 않은 유형은 원본 목록으로 넘긴다.
        if 있음:
            return RedirectResponse(f"/시설/전북/군산시/?유형={quote(유형)}", status_code=301)
        return HTMLResponse(tpl.get_template("404.html").render(ctx()), status_code=404)

    con = db()
    rows = con.execute("""
        SELECT f.*, t.capacity FROM facility f
        JOIN facility_type t ON t.code = f.code AND t.type = ?
        ORDER BY t.capacity DESC, f.name""", (유형,)).fetchall()
    유형별 = {r["type"]: r["c"] for r in con.execute(
        "SELECT type, COUNT(*) c FROM facility_type GROUP BY type")}
    전체수 = con.execute("SELECT COUNT(*) c FROM facility").fetchone()["c"]
    con.close()

    b = _유형_비용(유형)
    다른유형 = [(t, 유형별[t],
                f"/시설/전북/군산시/{quote(t)}/" if t in 경로유형 else f"/시설/전북/군산시/?유형={quote(t)}")
              for t in 유형순서 if t in 유형별]

    제목 = f"군산시 {유형} {len(rows)}곳 — 정원·비용 한 번에"
    요약 = (f"군산시 {유형} {len(rows)}곳 전체 목록. 국민건강보험공단 공개 자료 기준. "
            f"2026년 수가로 본인부담금을 함께 정리했습니다.")
    경로 = f"/시설/전북/군산시/{유형}/"

    # 유형마다 광고 자리가 다르다. 요양원 자리에 재가센터를 걸지 않는다.
    광고키 = {"요양원": "군산요양원:요양원", "방문요양": "군산방문요양:재가"}.get(유형, "")

    return tpl.TemplateResponse(request, "유형.html", ctx(
        rows=rows, 유형=유형, 총계=len(rows), 전체수=전체수, 다른유형=다른유형,
        광고키=광고키,
        유형설명=유형설명.get(유형, ""), fees=fees,
        비용요약=b.get("요약"), 비용설명=b.get("설명"),
        비용표=b.get("표"), 비용주의=b.get("주의"), 다음글=b.get("다음글"),
        제목=제목, 요약=요약, 색인=True, canonical=경로,
        스키마=[seo.데이터셋_스키마(DATA_기준일, DATA_URL, len(rows)),
              seo.이동경로_스키마([("요양지도", "/"),
                              ("군산시 요양시설", "/시설/전북/군산시/"),
                              (f"군산시 {유형}", 경로)])]))


@app.get("/시설/전북/군산시/{slug}", response_class=HTMLResponse)
def facility(request: Request, slug: str):
    con = db()
    f = con.execute("SELECT * FROM facility WHERE slug = ?", (slug,)).fetchone()
    if not f:
        con.close()
        return HTMLResponse(
            tpl.get_template("404.html").render(ctx(request=request)), status_code=404)
    ts = con.execute(
        "SELECT type, capacity FROM facility_type WHERE code = ?", (f["code"],)).fetchall()
    같은동 = con.execute("""
        SELECT name, slug, 대표유형, 대표정원 FROM facility
        WHERE dong = ? AND code != ? ORDER BY 대표정원 DESC LIMIT 6""",
        (f["dong"], f["code"])).fetchall()
    con.close()
    ts = sorted(ts, key=lambda r: 유형순서.index(r["type"]) if r["type"] in 유형순서 else 99)
    비용 = None
    if any(r["type"] in ("요양원", "공동생활가정") for r in ts):
        비용 = {g: fees.요양원_월비용(g) for g in ("1", "2", "3")}

    색인가능, 색인보류사유 = seo.시설_색인여부(f)
    메모 = seo.시설_메모(f)
    return tpl.TemplateResponse(request, "facility.html", ctx(
        f=f, ts=ts, 같은동=같은동, 유형설명=유형설명, 비용=비용, 메모=메모,
        색인=색인가능, 색인보류사유=색인보류사유,
        canonical=f"/시설/전북/군산시/{slug}"))


@app.get("/글/요양원-요양병원-차이", response_class=HTMLResponse)
def 글_요양원_요양병원(request: Request):
    표 = fees.노인요양시설
    발행일 = "2026-08-23"

    # FAQ는 화면에 그대로 보이는 것만 넣는다. 템플릿이 이 목록을 렌더링한다.
    qa = [
        ("요양원과 요양병원 중 어디가 더 쌉니까?",
         f"조건에 따라 뒤집힙니다. 2026년 요양원은 장기요양 1등급 기준 급여 본인부담이 "
         f"하루 {표['1']['본인부담']:,}원, 30일이면 {표['1']['본인부담']*30:,}원이고 여기에 식재료비 등 "
         "비급여가 붙습니다. 요양병원은 요양급여비용총액의 20%가 본인부담인데, "
         "'선택입원군'으로 분류되면 40%로 두 배가 되고 식대도 절반을 냅니다. "
         "여기에 간병비가 대부분 따로 붙습니다. "
         "출처: 건강보험심사평가원 건강보험 본인부담기준 안내(2026-06-23 수정), "
         "보건복지부 2026년도 장기요양 급여유형별 수가."),
        ("요양병원에 들어가려면 장기요양등급이 있어야 합니까?",
         "필요하지 않습니다. 요양병원은 「의료법」상 병원급 의료기관이라 건강보험으로 입원합니다. "
         "장기요양등급은 요양원·주야간보호·방문요양 같은 장기요양급여를 쓸 때 필요합니다. "
         "근거: 노인장기요양보험법 제23조(장기요양급여의 종류)."),
        ("'선택입원군'이 무슨 뜻입니까?",
         "건강보험심사평가원 본인부담 안내표에 나오는 요양병원 환자 분류 중 하나로, "
         "여기에 해당하면 본인부담률이 요양급여비용총액의 40%가 됩니다. "
         "일반환자 20%의 두 배입니다. 입원 상담을 하실 때 "
         "'저희 부모님은 어느 분류군으로 잡히나요'를 반드시 물어보셔야 하는 이유입니다."),
        ("요양병원에 오래 입원하면 비용이 더 듭니까?",
         "본인부담률이 올라갑니다. 16일 이상 입원하면 입원료 본인부담률이 16~30일은 5%, "
         "31일 이상은 10% 상향됩니다. 다만 장기입원이 불가피한 환자, 보훈, 산정특례, "
         "차상위 본인부담경감 환자는 제외됩니다. "
         "또 본인부담액상한제에서도 요양병원 입원일수가 120일을 넘는지에 따라 "
         "소득 1~5분위의 상한액이 달라집니다. "
         "근거: 국민건강보험법 시행령 별표2 제5호, 국민건강보험공단 본인부담액상한제 안내."),
        ("장기요양보험에 '요양병원간병비'가 있다고 들었습니다.",
         "조문에는 있습니다. 노인장기요양보험법 제26조는 "
         "'공단은 수급자가 「의료법」 제3조제2항제3호라목에 따른 요양병원에 입원한 때 "
         "대통령령으로 정하는 기준에 따라 장기요양에 사용되는 비용의 일부를 "
         "요양병원간병비로 지급할 수 있다'고 정합니다. "
         "다만 '지급할 수 있다'는 임의 규정입니다. 조문이 있다는 것과 실제로 지급된다는 것은 "
         "다르므로, 지금 받을 수 있는지는 국민건강보험공단 1577-1000에 확인하셔야 합니다."),
        ("요양원 본인부담금을 깎아주는 제도가 있습니까?",
         "있습니다. 의료급여 수급권자는 본인일부부담금의 60%를, "
         "소득·재산이 기준 이하인 분은 40% 또는 60%를 감경받습니다. "
         "1등급이면 한 달 558,420원이 223,368원까지 내려갑니다. "
         "대상이 되는 소득·재산 기준은 해마다 새로 고시되므로 직접 계산하실 필요 없이 "
         "국민건강보험공단 1577-1000에 전화하시면 대상인지 바로 알려줍니다. "
         "출처: 국민건강보험공단 장기요양보험료 및 본인부담금 안내."),
    ]

    인용 = [v["URL"] for v in compare.출처.values()] + [fees.출처URL]
    제목 = "요양원과 요양병원, 뭐가 다르고 한 달에 얼마나 차이 납니까 (2026년 기준)"
    요약 = ("요양원은 장기요양보험, 요양병원은 건강보험입니다. 2026년 요양원은 등급이 정해지면 "
            "전국 어디나 하루 금액이 같지만, 요양병원은 환자 분류와 입원 일수에 따라 "
            "본인부담률이 20%에서 40%까지 갈립니다. 1차 출처로 확인한 것과 확인하지 못한 것을 "
            "나눠 적었습니다.")

    return tpl.TemplateResponse(request, "글_요양원_요양병원.html", ctx(
        표=표, qa=qa, compare=compare, fees=fees, 발행일=발행일, 제목=제목, 요약=요약,
        색인=True, canonical="/글/요양원-요양병원-차이",
        스키마=[seo.글_스키마(제목, 요약, "/글/요양원-요양병원-차이", 발행일, 갱신일, 인용),
              seo.질문답변_스키마(qa),
              seo.이동경로_스키마([("요양지도", "/"),
                              ("요양원과 요양병원의 차이", "/글/요양원-요양병원-차이")])]))


@app.get("/글/요양병원-한달-비용", response_class=HTMLResponse)
def 글_요양병원_비용(request: Request):
    """검색량이 가장 큰 주제(요양병원 한달 비용 계열 월 2,400회, Ahrefs 2026-08-24).
    FAQ 항목은 실제 검색어에서 뽑았다 — 기초생활수급자·암·치매·간병비."""
    발행일 = "2026-08-24"

    qa = [
        ("요양병원 한 달 비용은 얼마인가요?",
         "전국 공통 금액이 없습니다. 요양원처럼 등급별로 정해진 하루 금액이 있는 것이 아니라, "
         "그 달에 발생한 요양급여비용총액에 본인부담률을 곱하는 방식이기 때문입니다. "
         "건강보험 가입자는 일반환자가 요양급여비용총액의 20%, 선택입원군으로 분류되면 40%이고, "
         "식대는 별도로 50%를 냅니다. 여기에 간병비가 대부분 전액 본인 부담으로 추가됩니다. "
         "출처: 건강보험심사평가원 건강보험 본인부담기준 안내(2026-06-23 수정)."),
        ("기초생활수급자는 요양병원 비용이 얼마인가요?",
         "의료급여 1종 수급권자는 제1·2·3차 의료급여기관 입원 진료비가 무료입니다. "
         "식대만 20%를 부담합니다. 2종 수급권자는 의료급여비용총액의 10%이며, "
         "2종 장애인은 장애인 의료비로 지원되어 무료입니다. "
         "다만 간병비와 상급병실료처럼 급여가 아닌 항목은 별도로 부담하셔야 합니다. "
         "출처: 건강보험심사평가원 의료급여 본인부담기준 안내(2026-07-30 수정)."),
        ("'선택입원군'이 무슨 뜻인가요?",
         "건강보험심사평가원 본인부담 안내표에 나오는 요양병원 환자 분류 중 하나입니다. "
         "여기에 해당하면 본인부담률이 요양급여비용총액의 40%가 되어 일반환자 20%의 두 배가 됩니다. "
         "같은 병실에서 같은 치료를 받아도 이 분류에 따라 내는 금액이 달라지므로, "
         "입원 상담에서 '저희 부모님은 어느 환자분류군으로 잡힙니까'를 반드시 물어보셔야 합니다."),
        ("암 환자는 요양병원 비용이 다른가요?",
         "다릅니다. 건강보험 가입자가 암 등 중증질환으로 산정특례에 등록되면 "
         "본인부담률이 요양급여비용총액의 5%로 내려갑니다. "
         "의료급여 수급권자도 중증질환자로 등록되면 5%이며, "
         "뇌혈관질환·심장질환·중증외상 중증질환자(2종)는 무료입니다. "
         "본인이 산정특례 대상인지는 국민건강보험공단 1577-1000에서 확인할 수 있습니다."),
        ("치매 환자는 어떻게 되나요?",
         "의료급여 2종 수급권자 중 치매질환자로 등록된 경우(특정기호 V800·V810) "
         "본인부담률이 의료급여비용총액의 5%입니다. "
         "건강보험 가입자의 치매는 별도의 일괄 감면이 아니라 산정특례 등록 여부에 따라 달라지므로 "
         "공단에 개별 확인이 필요합니다."),
        ("요양병원에 오래 입원하면 비용이 더 드나요?",
         "본인부담률이 올라갑니다. 16일 이상 입원하면 입원료 본인부담률이 "
         "16~30일은 5%, 31일 이상은 10% 상향됩니다. "
         "다만 장기입원이 불가피한 환자, 보훈, 산정특례, 차상위 본인부담경감 환자는 제외됩니다. "
         "또 본인부담액상한제에서도 요양병원 입원일수가 120일을 넘는지에 따라 "
         "소득 1~5분위의 상한액이 달라집니다. "
         "근거: 국민건강보험법 시행령 별표2 제5호."),
        ("간병비는 얼마나 드나요?",
         "정해진 금액이 없습니다. 간병비는 건강보험 급여가 아니어서 수가 자체가 존재하지 않고, "
         "병원이 정한 값이 곧 가격입니다. 개인 간병과 공동 간병은 단가가 크게 다르므로 "
         "입원하실 병원에 둘 다 하루 얼마인지 직접 물어보셔야 합니다. "
         "노인장기요양보험법 제26조에 '요양병원간병비' 조문이 있으나 '지급할 수 있다'는 임의 규정입니다."),
    ]

    인용 = [v["URL"] for v in hospital.출처.values()]
    제목 = "요양병원 한 달 비용, 실제로 얼마나 드나요 (2026년 기준)"
    요약 = ("요양병원은 전국 공통 금액이 없습니다. 일반환자는 요양급여비용총액의 20%, "
            "선택입원군은 40%, 식대는 50%입니다. 의료급여 1종은 진료비가 무료이고 식대 20%만 냅니다. "
            "심평원 자료로 확인한 것과 확인하지 못한 것을 나눠 적었습니다.")

    return tpl.TemplateResponse(request, "글_요양병원_비용.html", ctx(
        hospital=hospital, qa=qa, 발행일=발행일, 제목=제목, 요약=요약,
        색인=True, canonical="/글/요양병원-한달-비용",
        스키마=[seo.글_스키마(제목, 요약, "/글/요양병원-한달-비용", 발행일, 갱신일, 인용),
              seo.질문답변_스키마(qa),
              seo.이동경로_스키마([("요양지도", "/"),
                              ("요양병원 한 달 비용", "/글/요양병원-한달-비용")])]))


@app.get("/글/간병비", response_class=HTMLResponse)
def 글_간병비(request: Request):
    """간병비 계열 검색어(간병인 비용·간병인 일당·간호간병통합서비스 등)를 받는 글.
    보험 이야기는 넣지 않는다 — 간병비를 검색한 사람에게 보험을 파는 글은 이미 많다."""
    발행일 = "2026-08-25"
    c = caregiving
    월일반 = c.월환산(c.비교["일반병동"]["합계"])
    월통합 = c.월환산(c.비교["통합병동"]["합계"])
    월절감 = c.월환산(c.비교["절감_하루"])
    월간병비 = c.월환산(c.비교["일반병동"]["간병비"])

    qa = [
        ("간병비는 한 달에 얼마나 드나요?",
         f"정해진 값이 없습니다. 간병은 건강보험 급여 항목이 아니라 수가 자체가 존재하지 않고, "
         f"병원이나 간병인이 정한 값이 곧 가격입니다. "
         f"참고할 수 있는 공식 비교로는 국민건강보험공단이 2023년 9월 웹진에서 제시한 "
         f"종합병원 6인실 기준 개인 간병인 하루 {c.비교['일반병동']['간병비']:,}원"
         f"(30일 환산 약 {월간병비:,}원)이 있습니다. "
         f"다만 이는 2023년 기준이며 현재 금액과 다를 수 있습니다."),
        ("간병비를 줄이는 방법이 있나요?",
         f"간호간병통합서비스가 있습니다. 간호 인력이 24시간 돌보는 병동으로 건강보험이 적용되어 "
         f"간병인을 따로 쓰지 않아도 됩니다. 공단 비교에 따르면 종합병원 6인실 기준 "
         f"일반병동에 개인 간병인을 쓰면 하루 {c.비교['일반병동']['합계']:,}원인 반면 "
         f"간호간병통합병동은 하루 {c.비교['통합병동']['합계']:,}원으로, "
         f"한 달 약 {월절감:,}원 차이가 납니다. 공단은 이를 '{c.비교['감소율_문구']}'로 표현했습니다."),
        ("요양원에도 간병비가 드나요?",
         "요양원은 간병비를 따로 내지 않습니다. 요양보호사 인건비가 장기요양 수가 안에 "
         "이미 포함되어 있기 때문입니다. 요양원에서 별도로 부담하시는 것은 "
         "식재료비·상급침실 이용료·이미용비 같은 비급여 항목입니다. "
         "간병비가 별도로 드는 곳은 요양병원입니다."),
        ("요양병원에도 간호간병통합병동이 있나요?",
         "거의 없습니다. 공단 「간호·간병 통합서비스 병원 찾기」에서 서울 지역을 조회했을 때"
         "(2026-08-25 확인) 대학병원과 종합병원만 나오고 요양병원은 나오지 않았습니다. "
         "다만 이는 화면에서 확인한 것이며 규정을 확인한 것은 아니므로, "
         "국민건강보험공단 1577-1000에 문의하시는 것이 정확합니다."),
        ("나라에서 요양병원 간병비를 지원해 주나요?",
         "노인장기요양보험법 제26조에 '요양병원간병비' 조문이 있습니다. "
         "다만 '지급할 수 있다'는 임의 규정이어서 조문이 있다는 것과 실제로 지급된다는 것은 다릅니다. "
         "저희는 현재 지급 여부를 1차 출처로 확인하지 못했습니다. "
         "보건복지상담센터 129에 문의하시면 현재 상태를 알려줍니다."),
        ("개인 간병과 공동 간병은 무엇이 다른가요?",
         "공동 간병은 간병인 한 사람이 여러 환자를 함께 돌보는 방식이고, 개인 간병은 한 사람만 전담합니다. "
         "비용이 크게 다르므로 입원 상담에서 두 가지 단가를 각각 물어보셔야 합니다. "
         "또 주말과 명절에 금액이 올라가는 곳이 많으니 한 달 총액을 물으실 때 함께 확인하세요."),
    ]

    인용 = [v["URL"] for v in c.출처.values()]
    제목 = "간병비, 실제로 얼마나 드나요 (2026년 기준 정리)"
    요약 = ("간병비는 건강보험 급여가 아니라 정해진 값이 없습니다. 공단 비교로는 개인 간병인이 "
            "하루 101,207원, 간호간병통합병동은 하루 22,340원입니다. "
            "요양원에는 간병비가 없고 요양병원에는 통합병동이 거의 없습니다.")

    return tpl.TemplateResponse(request, "글_간병비.html", ctx(
        c=c, qa=qa, 발행일=발행일, 제목=제목, 요약=요약,
        월일반=월일반, 월통합=월통합, 월절감=월절감, 월간병비=월간병비,
        색인=True, canonical="/글/간병비",
        스키마=[seo.글_스키마(제목, 요약, "/글/간병비", 발행일, 갱신일, 인용),
              seo.질문답변_스키마(qa),
              seo.이동경로_스키마([("요양지도", "/"), ("간병비", "/글/간병비")])]))


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "\n".join([
        "# 요양지도 robots.txt",
        "# 검색·AI 크롤러 모두 환영합니다. 다만 필터가 걸린 주소는 원본과 겹치므로 제외합니다.",
        "",
        "User-agent: *",
        "Allow: /",
        "Disallow: /*?유형=",
        "Disallow: /*?등급=",
        "Disallow: /setup-",
        "",
        "# AI 검색 크롤러 — 인용되려면 읽을 수 있어야 합니다",
        "User-agent: GPTBot",
        "Allow: /",
        "User-agent: OAI-SearchBot",
        "Allow: /",
        "User-agent: ClaudeBot",
        "Allow: /",
        "User-agent: PerplexityBot",
        "Allow: /",
        "User-agent: Google-Extended",
        "Allow: /",
        "",
        "# 네이버",
        "User-agent: Yeti",
        "Allow: /",
        "",
        f"Sitemap: {DOMAIN}/sitemap.xml",
        "",
    ])


@app.get("/sitemap.xml")
def sitemap():
    """색인해도 되는 페이지만 넣는다.
    자동 생성된 시설 페이지는 사람이 확인한 것부터 하나씩 들어온다."""
    urls = [("/", "1.0"),
            ("/계산기/요양원-본인부담금", "0.9"),
            ("/글/요양원-요양병원-차이", "0.9"),
            ("/글/요양병원-한달-비용", "0.9"),
            ("/글/간병비", "0.9"),
            ("/시설/전북/군산시/", "0.8"),
            # 광고주(요양원·간병업체)가 검색으로 찾아와야 하는 페이지다.
            ("/광고안내", "0.6")]
    urls += [(f"/시설/전북/군산시/{t}/", "0.7") for t in 경로유형]
    con = db()
    for f in con.execute("SELECT * FROM facility"):
        ok, _ = seo.시설_색인여부(f)
        if ok:
            urls.append((f"/시설/전북/군산시/{f['slug']}", "0.5"))
    con.close()

    body = "".join(
        f"<url><loc>{절대주소(u).replace('&', '&amp;')}</loc>"
        f"<lastmod>{갱신일}</lastmod><priority>{p}</priority></url>"
        for u, p in urls)
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?>'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml")


# /색인정책 페이지는 없앴다.
# 색인 규칙은 seo.py가 계속 강제한다. 다만 그 규칙을 방문자에게 설명하는 페이지는
# 방문자가 궁금해할 내용이 아니고, 오히려 검색 노출이 목적인 사이트로 보이게 한다.
# 규칙이 지금 어떻게 적용되고 있는지는 아래 /setup- 경로에서 우리가 직접 본다.


@app.get("/setup-8f3a91c40b/색인", response_class=PlainTextResponse)
def 색인현황():
    """지금 몇 곳이 색인 대상인지. 우리만 본다."""
    con = db()
    행 = con.execute("SELECT * FROM facility").fetchall()
    con.close()
    켜짐 = [f for f in 행 if seo.시설_색인여부(f)[0]]
    사유 = {}
    for f in 행:
        ok, why = seo.시설_색인여부(f)
        if not ok:
            사유[why] = 사유.get(why, 0) + 1
    줄 = [f"시설 페이지 색인 현황  ({datetime.now(crawler.KST):%Y-%m-%d %H:%M} KST)",
          "=" * 62, "",
          f"전체 {len(행)}곳 중 색인 대상 {len(켜짐)}곳 (주간 상한 {seo.주간_색인_상한}곳)", ""]
    for why, n in sorted(사유.items(), key=lambda x: -x[1]):
        줄.append(f"  {n:>4}곳  {why}")
    if 켜짐:
        줄 += ["", "색인 켜진 곳:"] + [f"  {f['name']}" for f in 켜짐]
    return "\n".join(줄) + "\n"


@app.get("/setup-8f3a91c40b/크롤러", response_class=PlainTextResponse)
def 크롤러_기록보기():
    """어떤 크롤러가 실제로 다녀갔는가.
    robots.txt에서 /setup- 을 막아두었고, 이 페이지는 사람 정보를 담지 않는다."""
    행 = crawler.목록()
    줄 = [f"요양지도 크롤러 접속 기록  ({datetime.now(crawler.KST):%Y-%m-%d %H:%M} KST)",
          "=" * 62, ""]
    if not 행:
        줄 += ["아직 어떤 크롤러도 다녀가지 않았습니다.",
              "",
              "신규 도메인은 검수에 3~6주가 걸립니다. 제출했다는 것과",
              "수집됐다는 것은 다릅니다. 이 목록이 채워질 때가 수집이 시작된 때입니다."]
    else:
        줄.append(f"{'크롤러':<22}{'횟수':>6}   {'처음':<17}{'마지막':<17}마지막 경로")
        줄.append("-" * 62)
        for r in 행:
            줄.append(f"{r['이름']:<22}{r['횟수']:>6}   {r['처음']:<17}{r['마지막']:<17}{r['마지막경로']}")
    return "\n".join(줄) + "\n"


@app.get("/setup-8f3a91c40b/방문", response_class=PlainTextResponse)
def 방문현황():
    """사람이 몇 번 봤는가. 광고주에게 보여줄 근거가 되는 숫자다."""
    달들 = crawler.방문_요약()
    줄 = [f"요양지도 페이지 조회 수  ({datetime.now(crawler.KST):%Y-%m-%d %H:%M} KST)",
          "=" * 62,
          "순 방문자가 아니라 '페이지 조회 수'입니다. 개인을 식별하지 않습니다.", ""]
    if not 달들:
        줄.append("아직 사람이 다녀간 기록이 없습니다.")
    for m in 달들:
        줄.append(f"[{m['달']}]  합계 {m['합계']:,}회")
        for 경로, n in m["상위"]:
            줄.append(f"      {n:>6,}  {경로}")
        줄.append("")
    return "\n".join(줄) + "\n"


def _광고자리(키: str):
    """자리에 걸린 광고를 꺼내면서 노출을 1 센다.
    광고주에게 '지난달 노출 몇 회'를 못 보여주면 재계약이 안 된다."""
    걸린것 = ads.자리(키)
    if 걸린것:
        ads.노출(걸린것["id"])
    return 걸린것


@app.get("/광고/{ad_id}")
def 광고_클릭(ad_id: int):
    """유료 링크는 우리 주소를 한 번 거쳐 나간다. 클릭을 세기 위해서다.
    경로 파라미터 이름은 반드시 ASCII다. {게재id}로 쓰면 Starlette가
    파라미터로 인식하지 못하고 문자 그대로의 경로로 취급한다(2026-08-24, 08-26 두 번 겪음)."""
    주소 = ads.클릭(ad_id)
    if not 주소:
        return RedirectResponse("/광고안내", status_code=302)
    return RedirectResponse(주소, status_code=302)


@app.get("/광고안내", response_class=HTMLResponse)
def 광고안내(request: Request, 접수: str = Query("")):
    현황 = ads.전체현황()
    재고 = ads.재고()
    이번달 = crawler.방문_요약(1)
    월조회 = 이번달[0]["합계"] if 이번달 else 0
    return tpl.TemplateResponse(request, "광고안내.html", ctx(
        현황=현황, 재고=재고, 월조회=월조회, 접수=접수,
        유료개시=ads.유료개시_월조회,
        색인=True, canonical="/광고안내",
        스키마=[seo.이동경로_스키마([("요양지도", "/"), ("광고 안내", "/광고안내")])]))


@app.post("/광고문의")
async def 광고문의_접수(request: Request):
    """광고 문의를 받는다.

    FastAPI의 Form(...)을 쓰지 않는 이유:
      Form(...)은 python-multipart 패키지를 요구하는데, 서버 requirements.txt에
      그게 없어서 앱이 통째로 못 뜨고 502가 났다(2026-08-26 실제로 겪음).
      urlencoded 본문은 Starlette가 추가 패키지 없이 읽을 수 있다. 그래서 직접 읽는다.

    스팸을 막는 방법 세 가지. 사람에게는 아무것도 요구하지 않는다.
      1) 숨긴 칸(홈페이지) — 화면에 안 보이니 사람은 못 채운다. 로봇은 채운다.
      2) 시간당 상한 — 한 시간에 20건이 넘으면 자동 제출로 본다.
      3) 최소 조건 — 업체명과 연락처(전화 또는 메일) 중 하나는 있어야 한다.
    글자 맞추기(캡차)는 넣지 않는다. 어르신 시설 원장님들을 돌려보내게 된다.
    """
    양식 = await request.form()

    def 값(이름: str) -> str:
        return str(양식.get(이름, "") or "").strip()

    if 값("홈페이지"):
        return RedirectResponse("/광고안내?접수=1", status_code=303)   # 조용히 버린다
    if ads.최근_문의_수(60) >= 20:
        return RedirectResponse("/광고안내?접수=혼잡", status_code=303)

    업체명, 전화, 이메일 = 값("업체명"), 값("전화"), 값("이메일")
    if not 업체명 or not (전화 or 이메일):
        return RedirectResponse("/광고안내?접수=부족", status_code=303)

    번호 = ads.문의_저장(업체명, 값("자리"), 전화, 이메일, 값("한줄"), 값("하실말씀"))

    # 알림은 실패해도 접수는 성공이어야 한다.
    # 상세 내용은 보내지 않는다. "몇 번 문의가 들어왔다"까지만.
    설정 = {
        "채널": ads.설정_읽기("알림채널", "없음"),
        "주제": ads.설정_읽기("ntfy주제", ""),
        "토큰": ads.설정_읽기("텔레그램토큰", ""),
        "방": ads.설정_읽기("텔레그램방", ""),
    }
    보냄, 사유 = notify.알림(
        설정,
        "요양지도 · 새 광고 문의",
        f"{번호}번 문의가 들어왔습니다. 관리 화면에서 확인하세요.",
        f"{DOMAIN}/setup-8f3a91c40b/문의")
    ads.설정_쓰기("마지막알림", f"{번호}번 · {'보냄' if 보냄 else '실패'} · {사유}")

    return RedirectResponse("/광고안내?접수=1", status_code=303)


@app.get("/setup-8f3a91c40b/문의", response_class=PlainTextResponse)
def 문의현황(읽음: str = Query("")):
    if 읽음 == "처리":
        n = ads.문의_읽음처리()
        return f"{n}건을 읽음으로 바꿨습니다.\n"
    목록 = ads.문의_목록()
    줄 = [f"요양지도 광고 문의  ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
          "=" * 74,
          f"전체 {len(목록)}건 · 안읽음 {ads.문의_안읽음()}건",
          f"마지막 알림: {ads.설정_읽기('마지막알림', '아직 없음')}",
          "전부 읽음으로 바꾸려면 이 주소 뒤에 ?읽음=처리 를 붙이세요.",
          "-" * 74]
    if not 목록:
        줄.append("아직 들어온 문의가 없습니다.")
    for m in 목록:
        줄 += [
            f"[{m['id']}] {m['받은때']}  {m['상태']}",
            f"  업체   {m['업체명']}",
            f"  자리   {m['자리키'] or '(안 고름)'}",
            f"  연락   {m['전화'] or '-'} / {m['이메일'] or '-'}",
            f"  한줄   {m['한줄'] or '-'}",
            f"  말씀   {(m['하실말씀'] or '-')[:300]}",
            "-" * 74,
        ]
    return "\n".join(줄) + "\n"


@app.get("/setup-8f3a91c40b/알림", response_class=PlainTextResponse)
def 알림설정(채널: str = Query(""), 주제: str = Query(""),
           토큰: str = Query(""), 방: str = Query(""), 시험: str = Query("")):
    """알림 통로를 여기서 켜고 끈다. 서버에 직접 들어가지 않아도 되게 만들었다."""
    if 채널:
        ads.설정_쓰기("알림채널", 채널)
    if 주제:
        ads.설정_쓰기("ntfy주제", 주제)
    if 토큰:
        ads.설정_쓰기("텔레그램토큰", 토큰)
    if 방:
        ads.설정_쓰기("텔레그램방", 방)

    설정 = {
        "채널": ads.설정_읽기("알림채널", "없음"),
        "주제": ads.설정_읽기("ntfy주제", ""),
        "토큰": ads.설정_읽기("텔레그램토큰", ""),
        "방": ads.설정_읽기("텔레그램방", ""),
    }
    줄 = ["요양지도 알림 설정", "=" * 60,
          f"채널      {설정['채널']}",
          f"ntfy 주제  {설정['주제'] or '(비어 있음)'}",
          f"텔레그램   {'설정됨' if 설정['토큰'] else '(비어 있음)'}",
          f"마지막 알림 {ads.설정_읽기('마지막알림', '아직 없음')}",
          "-" * 60]
    if 시험 == "1":
        보냄, 사유 = notify.알림(설정, "요양지도 · 알림 시험",
                             "이 알림이 보이면 설정이 끝난 것입니다.",
                             f"{DOMAIN}/setup-8f3a91c40b/문의")
        줄.append(f"시험 발송: {'성공' if 보냄 else '실패'} — {사유}")
    else:
        줄.append("시험 발송하려면 이 주소 뒤에 ?시험=1 을 붙이세요.")
    return "\n".join(줄) + "\n"


@app.get("/setup-8f3a91c40b/광고", response_class=PlainTextResponse)
def 광고현황():
    줄 = [f"요양지도 배너 자리 현황  ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
          "=" * 74]
    r = ads.재고()
    줄.append(f"자리 {r['총자리']}개 · 판매 {r['판매됨']} · 빈자리 {r['빈자리']}")
    줄.append(f"다 팔면 월 {r['정가합계']:,}원 · 지금 비어 있는 값 월 {r['미판매액']:,}원")
    줄.append("-" * 74)
    줄.append(f"{'자리':<26}{'대상':<22}{'월단가':>9}  {'업체':<12}{'노출':>6}{'클릭':>6}")
    for x in ads.전체현황():
        줄.append(f"{x['키']:<26}{x['대상']:<22}{x['월단가']:>9,}  "
                  f"{(x['업체'] or '— 빈자리'):<12}{x['성과']['노출']:>6}{x['성과']['클릭']:>6}")
    return "\n".join(줄) + "\n"


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
