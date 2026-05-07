# 자가 진단 및 학습형 인과관계 기반 주식 자동매매 시스템
# Causal-Web Self-Diagnosing Stock Trading AI

> Claude Code가 매 세션 시작 시 자동으로 읽는 영구 컨텍스트입니다.
> 이 파일을 절대 요약하거나 생략하지 말 것. 전체를 읽고 작업을 시작할 것.

---

## 1. 프로젝트 목적 및 철학

단순한 기술적 지표 매매를 넘어, **시장 사건(Event)과 산업 간의 인과관계를 분석**하고,
스스로의 판단을 복기하며 로직을 수정하는 **자가 진단형 투자 AI**를 구축한다.

두 개의 핵심 논리 레이어로 구성된다:
- **[Mer's Logic]**: 사건 → 산업 → 기업으로 이어지는 인과관계 거미줄 + 자가 피드백
- **[Buffett's Logic]**: 과거 시점 정보 대칭 조건에서의 블라인드 테스트 + 대가 논리 학습

---

## 2. 시스템 아키텍처 (모듈 구성)

```
~/Desktop/FTTS/
│
├── CLAUDE.md                        ← 이 파일
├── README.md
├── requirements.txt
├── .env                             ← API 키 (git 제외)
├── .env.example
├── .gitignore
│
├── config/
│   ├── settings.py                  ← 전역 설정, 임계값, 파라미터
│   └── source_grades.yaml           ← 정보원 등급 초기값 (S~D)
│
├── data/
│   ├── raw/                         ← 수집된 원본 뉴스, 포스팅
│   ├── processed/                   ← 전처리된 이벤트 데이터
│   └── backtest/                    ← 버핏 블라인드 테스트용 과거 데이터
│
├── database/
│   ├── schema.sql                   ← PostgreSQL 스키마
│   ├── models.py                    ← SQLAlchemy ORM 모델
│   └── db_manager.py                ← DB 연결 및 CRUD
│
├── core/
│   ├── causal_graph.py              ← [핵심] 인과관계 지식 그래프
│   ├── weight_engine.py             ← [핵심] 가중치 계산 및 매매 판단
│   ├── self_feedback.py             ← [핵심] Self-Review Loop
│   └── source_grader.py             ← [핵심] 정보원 S~D 등급 채점
│
├── data_collection/
│   ├── news_crawler.py              ← 뉴스 실시간 수집
│   ├── blog_scraper.py              ← 블로그 '메르' 스크래퍼
│   └── stock_price_fetcher.py       ← 주가 데이터 수집
│
├── nlp/
│   ├── event_extractor.py           ← 이벤트 추출
│   ├── entity_linker.py             ← 기업/산업명 정규화
│   └── sentiment_analyzer.py        ← 감성 분석
│
├── trading/
│   ├── paper_trader.py              ← 모의 투자 실행
│   ├── live_trader.py               ← 실전 자동매매 (금지 상태)
│   ├── position_manager.py          ← 포지션 관리
│   └── risk_manager.py              ← 리스크 관리
│
├── backtest/
│   ├── buffett_simulator.py         ← 버핏 블라인드 테스트
│   ├── time_machine.py              ← 과거 시점 재현
│   └── performance_evaluator.py     ← 성능 비교
│
├── monitoring/
│   ├── dashboard.py                 ← Streamlit 대시보드
│   ├── accuracy_tracker.py          ← 정확도 추적 (80% 임계값)
│   └── alert_manager.py             ← 텔레그램 알림
│
└── tests/
    ├── test_causal_graph.py
    ├── test_weight_engine.py
    ├── test_self_feedback.py
    └── test_source_grader.py
```

---

## 3. 핵심 수학적 모델

### 가중치 업데이트 (Self-Feedback Loop)
```
결정 시 예측 가중치: W_predicted(x)
실제 시장 영향도:   W_actual(y)
오차:               ε = y - x

가중치 업데이트:
    W_new = W_old + α × ε × confidence_factor

여기서:
    α = 학습률 (기본값 0.1)
    confidence_factor = 정보원 등급 가중치
        S=1.0, A=0.8, B=0.6, C=0.4, D=0.2

정확도 누적:
    accuracy = correct_predictions / total_predictions
    → accuracy ≥ 0.80 이면 모의 → 실전 전환 검토
```

### 복합 이벤트 스코어링
```
event_score = Σ (edge_weight_i × source_grade_i × recency_decay_i)

recency_decay = exp(-0.05 × days_since_event)

최종 신호:
    score > BUY_THRESHOLD  → 매수
    score < SELL_THRESHOLD → 매도
    그 외 → 관망
```

---

## 4. 정보원 등급(S~D) 채점 로직

```
초기 등급: 신규 정보원 → C등급
최소 유효 예측: 10건 이상

등급 산출:
    S: accuracy >= 0.90
    A: accuracy >= 0.75
    B: accuracy >= 0.60
    C: accuracy >= 0.45
    D: accuracy < 0.45

의사결정 가중치:
    {S: 1.0, A: 0.8, B: 0.6, C: 0.4, D: 0.2}

특수 규칙:
    - 10건 미만: grade_weight = 0.5 (중립)
    - D등급 3회 연속: 자동 비활성화 + 알림
    - S등급 우선순위 처리
```

---

## 5. 개발 단계 (Phase)

```
Phase 1 — 기반 구축 (✅ 완료)
    ✅ CLAUDE.md 작성
    ✅ requirements.txt 작성
    ✅ schema.sql 생성
    ✅ SQLAlchemy 모델 정의
    ✅ DB 매니저 구현 (SQLite/PostgreSQL 자동 감지)

Phase 2 — 데이터 수집 (✅ 완료)
    ✅ 메르 블로그 스크래퍼
    ✅ 뉴스 수집 파이프라인
    ✅ 주가 데이터 수집 (yfinance + 샘플 주가 생성기)
    ✅ NLP 이벤트 추출 (GPT-4 기반)
    ✅ NLP 기업/산업명 정규화
    ✅ NLP 감성 분석

Phase 3 — 핵심 엔진 (✅ 완료)
    ✅ 인과관계 지식 그래프 + 테스트
    ✅ 가중치 계산 엔진 + 테스트
    ✅ Self-Feedback Loop + 테스트
    ✅ 정보원 S~D 등급 채점 + 테스트

Phase 4 — 모의 투자 (✅ 완료)
    ✅ 모의 매매 실행 (paper_trader.py, 7/7 테스트)
    ✅ 정확도 모니터링 (accuracy_tracker.py, 8/8 테스트)
    ✅ 버핏 블라인드 테스트 (buffett_simulator.py, 10/10 테스트)
    ✅ 시드 데이터 (종목 10개, 주가 8,730건)

Phase 5 — 정보원 확장 + Claude NLP 교체 (🔄 진행 중)
    ⬜ Claude API로 NLP 교체 (event_extractor, sentiment_analyzer)
    ⬜ DART API 전자공시 수집
    ⬜ Fed 홈페이지 크롤러 (연설문, FOMC 의사록)
    ⬜ SEC EDGAR 크롤러
    ⬜ 트럼프 X(트위터) 스크랩 (C등급 정보원)
    ⬜ 이벤트 → 인과관계 자동 연결 로직
    ⬜ Streamlit 대시보드 완성
    ⬜ APScheduler 전체 파이프라인 자동화

Phase 6 — 실전 전환 (정확도 ≥ 80% 확인 후)
    ⬜ KIS API 연동
    ⬜ 리스크 매니저
    ⬜ 텔레그램 알림
```

---

## 6. 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| DB | SQLite (개발) / PostgreSQL 15 (운영) + SQLAlchemy 2.0 |
| 그래프 | NetworkX |
| AI/NLP | Claude API (Sonnet 4.6) — 모든 분석/판단 담당 |
| 주가 | yfinance, KIS Open API |
| 정보원 | 메르 블로그, 뉴스 크롤러, DART API, Fed 홈페이지, SEC EDGAR, X(트위터) |
| 스케줄러 | APScheduler (15~30분 간격 자동 실행) |
| 대시보드 | Streamlit (localhost:8501) |
| 테스트 | pytest |

---

## 7. 개발 규칙 (YOU MUST)

### 작업 방식
- **YOU MUST**: 한 번에 하나의 모듈만 작성
- **YOU MUST**: 새 함수 작성 후 반드시 테스트도 함께 작성
- **YOU MUST**: 파라미터는 하드코딩 금지 → config/settings.py 또는 .env에서 로드
- **IMPORTANT**: live_trader.py는 정확도 80% 확인 전까지 절대 실행 금지

### 에러 처리
- API 실패 → 재시도 3회 → 로그 기록 → 알림
- DB 트랜잭션은 반드시 rollback 포함
- 에러 메시지 suppress 절대 금지
- 에러 발생 시 근본 원인부터 해결

### 보안
- .env 파일 git 커밋 금지
- 로그에 API 키, 계좌번호 출력 금지

---

## 8. 자주 쓰는 명령어

```bash
# 환경 설치
pip install -r requirements.txt

# DB 초기화
python -m database.db_manager --init

# 모의 투자 실행
python -m trading.paper_trader --run

# 정확도 리포트
python -m monitoring.accuracy_tracker --report

# 테스트
pytest tests/test_causal_graph.py -v

# 대시보드
streamlit run monitoring/dashboard.py
```

---

## 9. 현재 작업 컨텍스트

- **현재 Phase**: Phase 5 — 정보원 확장 + Claude NLP 교체 (진행 중)
- **완료된 것**: Phase 1~4 전부 완료
  - ✅ trading/paper_trader.py (7/7 테스트)
  - ✅ monitoring/accuracy_tracker.py (8/8 테스트)
  - ✅ backtest/buffett_simulator.py (10/10 테스트)
  - ✅ 시드 데이터: 10 종목 × 873 거래일 = 8,730 주가 기록
- **다음 작업**: Claude NLP 교체 + 정보원 확장
  - nlp/event_extractor.py → Claude API
  - nlp/sentiment_analyzer.py → Claude API
  - data_collection/dart_crawler.py (신규)
  - data_collection/fed_crawler.py (신규)
  - data_collection/sec_crawler.py (신규)
  - data_collection/trump_scraper.py (신규)
- **아키텍처 결정**:
  - 모든 NLP/분석: Claude Sonnet 4.6 (GPT-4 제거)
  - DB: SQLite 개발 + PostgreSQL 운영 자동 감지
  - 스케줄링: APScheduler 15~30분 간격
  - 대시보드: Streamlit (localhost:8501)
- **알려진 이슈**: Python 3.10+ 필수
