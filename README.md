# 요양지도

요양·간병 보호자를 위한 중립 정보 인프라.

## 이 저장소에 있는 것
- `app.py` — 웹사이트 본체 (FastAPI)
- `fees.py` — **2026년 장기요양 수가.** 출처: 보건복지부 「2026년도 장기요양보험료율 0.9448%」(2025-11-04 의결) 붙임2
- `build_db.py` — 공단 공개데이터(xlsx) → SQLite
- `data/장기요양기관_시설별현황.xlsx` — 국민건강보험공단 공개데이터 (기준일 2026-06-10, 이용허락범위 제한 없음)
- `templates/`, `static/` — 화면
- `deploy/startup.sh` — Vultr 서버 시작 스크립트

## 규칙
1. `fees.py`의 숫자는 **1차 출처에 없으면 넣지 않는다.** 추정 금지.
2. 모든 화면 상단에 **기준일 + 출처**를 적는다.
3. 시설에 순위·평점을 매기지 않는다. 공단 자료를 그대로 옮긴다.
4. 광고비를 받은 자리에는 반드시 "광고"라고 적는다. 알선 수수료는 받지 않는다.
   (노인장기요양보험법 제35조 제6항 / 제67조 제2항 제4호)

## 로컬에서 돌려보기
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build_db.py data/장기요양기관_시설별현황.xlsx 군산
.venv/bin/uvicorn app:app --reload
```
