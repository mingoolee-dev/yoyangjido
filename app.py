"""요양지도 — 요양·간병 보호자를 위한 중립 정보 인프라"""
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import fees
import seo

BASE = Path(__file__).parent
DB = BASE / "yoyangjido.db"
SITE = "요양지도"
DOMAIN = "https://yoyangjido.com"
DATA_기준일 = "2026-06-10"
갱신일 = "2026-08-23"          # 페이지 하단·스키마에 노출. 손볼 때마다 올린다.
DATA_출처 = "국민건강보험공단 장기요양기관 시설별 현황"
DATA_URL = "https://www.data.go.kr/data/15124763/fileData.do"
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
여정단계 = ["걱정 시작", "등급 신청", "시설 선택", "모시는 중", "그 이후"]

app = FastAPI(title=SITE, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
tpl = Jinja2Templates(directory=BASE / "templates")
tpl.env.filters["won"] = lambda v: f"{int(v):,}"
tpl.env.filters["jsonld"] = lambda d: json.dumps(d, ensure_ascii=False, separators=(",", ":"))


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ctx(**kw):
    base = {
        "SITE": SITE, "DOMAIN": DOMAIN, "여정단계": 여정단계,
        "DATA_기준일": DATA_기준일, "DATA_출처": DATA_출처, "DATA_URL": DATA_URL,
        "갱신일": 갱신일, "네이버_소유확인": 네이버_소유확인,
        # 기본은 색인 금지. 켤 페이지에서만 명시적으로 뒤집는다.
        "색인": False, "canonical": None, "스키마": [],
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
         "본인부담금 감경 제도가 있어 일반 대상자보다 적게 냅니다. "
         "다만 2026년 기준 감경 금액을 1차 출처로 확인하기 전에는 이 사이트에 금액을 적지 않습니다. "
         "관할 국민건강보험공단 지사(1577-1000)에 문의하시는 것이 정확합니다."),
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
    urls = [("/", "1.0"), ("/계산기/요양원-본인부담금", "0.9"), ("/시설/전북/군산시/", "0.8")]
    con = db()
    for f in con.execute("SELECT * FROM facility"):
        ok, _ = seo.시설_색인여부(f)
        if ok:
            urls.append((f"/시설/전북/군산시/{f['slug']}", "0.5"))
    con.close()

    def esc(u: str) -> str:
        return u.replace("&", "&amp;")

    body = "".join(
        f"<url><loc>{esc(DOMAIN + u)}</loc>"
        f"<lastmod>{갱신일}</lastmod><priority>{p}</priority></url>"
        for u, p in urls)
    return Response(
        content='<?xml version="1.0" encoding="UTF-8"?>'
                f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml")


@app.get("/색인정책", response_class=HTMLResponse)
def 색인정책(request: Request):
    con = db()
    총계 = con.execute("SELECT COUNT(*) c FROM facility").fetchone()["c"]
    색인수 = sum(1 for f in con.execute("SELECT * FROM facility") if seo.시설_색인여부(f)[0])
    con.close()
    return tpl.TemplateResponse(request, "policy.html", ctx(
        총계=총계, 색인수=색인수, 상한=seo.주간_색인_상한,
        색인=True, canonical="/색인정책"))


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
