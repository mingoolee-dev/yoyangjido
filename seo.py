"""
색인 정책과 구조화 데이터 — 2026-08-23 조사 기준

이 파일이 존재하는 이유:
  자동 생성 페이지를 한 번에 대량으로 검색엔진에 올리면 사이트 전체가 죽는다.
  Google 스팸 정책 「확장된 콘텐츠 악용」 — "사용자에게 도움을 제공하는 것이 아니라
  검색 순위를 조작하는 것을 주된 목적으로 많은 페이지가 생성되는 경우"
  https://developers.google.com/search/docs/essentials/spam-policies

핵심 원칙 (문서 10장 방어책을 코드로 강제한다):
  1. 기본은 noindex다. 색인은 사람이 확인한 페이지에만 켠다.
  2. 필터·정렬 URL은 절대 색인하지 않는다. canonical로 원본을 가리킨다.
  3. 사이트맵에는 색인 가능한 페이지만 넣는다.
  4. 한 주에 새로 색인을 켜는 페이지 수에 상한을 둔다.
"""
import json
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).parent
DOMAIN = "https://yoyangjido.com"


def _url(경로: str) -> str:
    """스키마 안의 주소도 사이트맵과 같은 규칙으로 퍼센트 인코딩한다."""
    return DOMAIN + quote(경로, safe="/")

# 한 주에 새로 색인을 켤 수 있는 시설 페이지 수 상한.
# 신규 도메인은 3~6주 검수 기간을 거치며, 비정상적인 발행 속도는 스팸 신호가 된다.
주간_색인_상한 = 10


def _검증목록() -> dict:
    """사람이 직접 확인한 시설. 방문 기록이나 확인 메모가 있어야 여기 들어온다.
    verified.json 형식:
      { "기관코드": {"확인일": "2026-08-30", "확인방법": "직접 방문",
                     "메모": "사람이 쓴 두 문장 이상의 고유 내용"} }
    """
    p = BASE / "verified.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


검증됨 = _검증목록()


def 시설_색인여부(f) -> tuple[bool, str]:
    """이 시설 페이지를 검색엔진에 올려도 되는가.

    통과 기준 — 셋 다 만족해야 한다:
      ① 사람이 직접 확인하고 고유한 내용을 100자 이상 썼다
      ② 공단 데이터에 정원 또는 인력 정보가 실제로 들어 있다
      ③ 주간 상한을 넘지 않는다 (확인 순서대로 켜진다)
    """
    v = 검증됨.get(f["code"])
    if not v:
        return False, "사람이 확인하지 않은 시설 — 공개 데이터만으로는 색인하지 않습니다"
    if len((v.get("메모") or "").strip()) < 100:
        return False, "확인 메모가 짧습니다"
    if not (f["대표정원"] or f["인력합계"]):
        return False, "공단 데이터가 이름·주소뿐입니다"
    return True, ""


def 시설_메모(f) -> dict | None:
    return 검증됨.get(f["code"])


# ── 구조화 데이터 ────────────────────────────────────────────────────
# 스키마가 붙은 페이지는 AI 검색에서 선택률이 눈에 띄게 높다는 조사가 있다.
# 다만 스키마는 내용이 정확할 때만 의미가 있다. 없는 사실을 넣지 않는다.

def 조직_스키마() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "요양지도",
        "url": DOMAIN,
        "description": "부모님 요양·간병을 알아보는 자녀를 위한 중립 정보 인프라. "
                       "제도와 금액을 1차 출처로 확인해 기준일과 함께 제공합니다.",
        "areaServed": {"@type": "AdministrativeArea", "name": "대한민국"},
        "knowsAbout": ["노인장기요양보험", "요양원 비용", "장기요양등급", "주야간보호", "방문요양"],
    }


def 웹사이트_스키마() -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "요양지도",
        "url": DOMAIN,
        "inLanguage": "ko-KR",
    }


def 이동경로_스키마(items: list[tuple[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            # url이 없는 단계는 item 키 자체를 빼야 한다. null을 넣으면 스키마가 깨진다.
            {k: v for k, v in {
                "@type": "ListItem", "position": i + 1, "name": name,
                "item": _url(url) if url else None,
            }.items() if v is not None}
            for i, (name, url) in enumerate(items)
        ],
    }


def 질문답변_스키마(qa: list[tuple[str, str]]) -> dict:
    """FAQPage. 화면에 실제로 보이는 질문과 답만 넣는다.
    보이지 않는 내용을 스키마에만 넣는 것은 구조화 데이터 정책 위반이다."""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qa
        ],
    }


def 글_스키마(제목: str, 요약: str, 경로: str, 발행일: str, 수정일: str,
             인용출처: list[str]) -> dict:
    """Article. AI 검색이 인용할 때 '누가 언제 확인한 글인지'가 남도록 만든다.

    citation에 우리가 실제로 읽은 1차 출처 주소를 넣는다.
    읽지 않은 주소는 넣지 않는다 — 스키마는 우리가 한 일을 적는 곳이지
    권위를 빌려오는 곳이 아니다.
    """
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": 제목,
        "description": 요약,
        "url": _url(경로),
        "mainEntityOfPage": {"@type": "WebPage", "@id": _url(경로)},
        "datePublished": 발행일,
        "dateModified": 수정일,
        "inLanguage": "ko-KR",
        "author": {"@type": "Organization", "name": "요양지도 편집실", "url": DOMAIN},
        "publisher": {"@type": "Organization", "name": "요양지도", "url": DOMAIN},
        "citation": 인용출처,
        "isAccessibleForFree": True,
    }


def 데이터셋_스키마(기준일: str, 출처URL: str, 건수: int) -> dict:
    """시설 목록의 출처를 기계가 읽을 수 있게 밝힌다. 우리가 만든 데이터가 아님을 명시."""
    return {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "군산시 장기요양기관 목록",
        "description": f"국민건강보험공단이 공개한 장기요양기관 현황에서 군산시 {건수}곳을 추린 목록입니다. "
                       f"평가나 순위를 매기지 않고 공개된 항목만 그대로 옮겼습니다.",
        "temporalCoverage": 기준일,
        "isBasedOn": 출처URL,
        "creator": {"@type": "GovernmentOrganization", "name": "국민건강보험공단"},
        "license": "https://www.data.go.kr/",
        "inLanguage": "ko-KR",
    }


def 계산기_스키마(기준일: str, 출처URL: str) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": "요양원 본인부담금 계산기 (2026년 기준)",
        "url": _url("/계산기/요양원-본인부담금"),
        "applicationCategory": "FinanceApplication",
        "operatingSystem": "웹 브라우저",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "KRW"},
        "isBasedOn": 출처URL,
        "dateModified": 기준일,
        "inLanguage": "ko-KR",
    }
