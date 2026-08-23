"""요양지도 — 요양·간병 보호자를 위한 중립 정보 인프라"""
import sqlite3, math
from pathlib import Path
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import fees

BASE = Path(__file__).parent
DB = BASE / "yoyangjido.db"
SITE = "요양지도"
DOMAIN = "https://yoyangjido.com"
DATA_기준일 = "2026-06-10"
DATA_출처 = "국민건강보험공단 장기요양기관 시설별 현황"
DATA_URL = "https://www.data.go.kr/data/15124763/fileData.do"

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


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def ctx(**kw):
    return {"SITE": SITE, "여정단계": 여정단계, "DATA_기준일": DATA_기준일,
            "DATA_출처": DATA_출처, "DATA_URL": DATA_URL, **kw}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    con = db()
    총계 = con.execute("SELECT COUNT(*) c FROM facility").fetchone()["c"]
    유형별 = {r["type"]: r["c"] for r in con.execute(
        "SELECT type, COUNT(*) c FROM facility_type GROUP BY type")}
    con.close()
    순 = [(t, 유형별[t]) for t in 유형순서 if t in 유형별]
    return tpl.TemplateResponse(request, "index.html", ctx(총계=총계, 유형별=순))


@app.get("/계산기/요양원-본인부담금", response_class=HTMLResponse)
def calc(request: Request,
         등급: str = Query("", alias="등급"),
         일수: int = Query(30, ge=1, le=31),
         비급여: int = Query(0, ge=0, le=5_000_000)):
    결과 = None
    if 등급 in fees.노인요양시설:
        결과 = fees.요양원_월비용(등급, 일수, 비급여)
    return tpl.TemplateResponse(request, "calc.html", ctx(결과=결과, 등급=등급, 일수=일수, 비급여=비급여,
        표=fees.노인요양시설, fees=fees))


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
    return tpl.TemplateResponse(request, "region.html", ctx(rows=rows, 유형=유형, 유형별=순, 유형설명=유형설명,
        총계=sum(유형별.values())))


@app.get("/시설/전북/군산시/{slug}", response_class=HTMLResponse)
def facility(request: Request, slug: str):
    con = db()
    f = con.execute("SELECT * FROM facility WHERE slug = ?", (slug,)).fetchone()
    if not f:
        con.close()
        return HTMLResponse(tpl.get_template("404.html").render(ctx(request=request)), status_code=404)
    ts = con.execute(
        "SELECT type, capacity FROM facility_type WHERE code = ?", (f["code"],)).fetchall()
    같은동 = con.execute("""
        SELECT name, slug, 대표유형, 대표정원 FROM facility
        WHERE dong = ? AND code != ? ORDER BY 대표정원 DESC LIMIT 6""",
        (f["dong"], f["code"])).fetchall()
    con.close()
    ts = sorted(ts, key=lambda r: 유형순서.index(r["type"])
                if r["type"] in 유형순서 else 99)
    비용 = None
    if any(r["type"] in ("요양원", "공동생활가정") for r in ts):
        비용 = {g: fees.요양원_월비용(g) for g in ("1", "2", "3")}
    return tpl.TemplateResponse(request, "facility.html", ctx(f=f, ts=ts, 같은동=같은동, 유형설명=유형설명, 비용=비용))


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return f"User-agent: *\nAllow: /\nSitemap: {DOMAIN}/sitemap.xml\n"


@app.get("/sitemap.xml")
def sitemap():
    con = db()
    slugs = [r["slug"] for r in con.execute("SELECT slug FROM facility")]
    con.close()
    urls = ["/", "/계산기/요양원-본인부담금", "/시설/전북/군산시/"] + \
           [f"/시설/전북/군산시/{s}" for s in slugs]
    body = "".join(f"<url><loc>{DOMAIN}{u}</loc></url>" for u in urls)
    return HTMLResponse(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>',
        media_type="application/xml")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
