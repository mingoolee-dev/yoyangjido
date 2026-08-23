"""요양지도 — 요양·간병 보호자를 위한 중립 정보 인프라"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import compare
import crawler
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

crawler.준비()


@app.middleware("http")
async def 크롤러_기록(request: Request, call_next):
    """검색·AI 크롤러가 실제로 왔는지만 남긴다. 사람 방문자는 기록하지 않는다."""
    crawler.기록(request.headers.get("user-agent", ""), request.url.path)
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


def ctx(**kw):
    base = {
        "SITE": SITE, "DOMAIN": DOMAIN, "여정단계": 여정단계,
        "DATA_기준일": DATA_기준일, "DATA_출처": DATA_출처, "DATA_URL": DATA_URL,
        "갱신일": 갱신일, "네이버_소유확인": 네이버_소유확인, "절대주소": 절대주소,
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
            ("/시설/전북/군산시/", "0.8")]
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


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
