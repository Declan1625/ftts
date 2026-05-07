# FTTS (For The Time of Soul)

자가 진단 및 학습형 인과관계 기반 주식 자동매매 시스템

## 개요

단순한 기술적 지표 매매를 넘어, **시장 사건(Event)과 산업 간의 인과관계를 학습**하고,
스스로의 판단을 복기하며 알고리즘을 개선하는 **자가 진단형 투자 AI**를 구축하는 프로젝트입니다.

## 두 가지 핵심 로직

### 1. Mer's Logic (인과관계 거미줄)
- 블로그 '메르'의 과거 포스팅을 학습하여 사건 → 산업 → 기업으로 이어지는 인과관계 지식 그래프 구축
- 실시간 뉴스/이벤트에서 가중치를 계산하여 매수/매도 신호 생성
- Self-Feedback Loop로 예측 오차를 학습, 가중치를 자동으로 보정
- 정보원별 S~D 등급제로 신뢰도 기반 의사결정 실현

### 2. Buffett's Logic (과거 회귀형 검증)
- 특정 과거 시점으로 데이터 환경을 설정하고, 당시 공개 정보만 제공 (정보 대칭성 준수)
- 블라인드 테스트: 미래를 모른 상태에서 AI의 판단을 먼저 기록
- 실제 버핏의 투자 결과와 비교하여 알고리즘 정교화

## 개발 로드맵

- **Phase 1**: 기반 구축 (DB 스키마, SQLAlchemy 모델, 기본 모듈)
- **Phase 2**: 데이터 수집 (메르 블로그 스크래퍼, 뉴스 수집, 주가 데이터)
- **Phase 3**: 핵심 엔진 (가중치 계산, Self-Feedback, 정보원 등급)
- **Phase 4**: 모의 투자 (Paper Trading, 정확도 추적)
- **Phase 5**: 실전 전환 (정확도 ≥ 80% 달성 후 실전 매매)

## 기술 스택

- **언어**: Python 3.11+
- **DB**: PostgreSQL 15 + SQLAlchemy 2.0 (개발 시 SQLite 가능)
- **그래프**: NetworkX
- **NLP**: Claude Sonnet 4.6 (Anthropic SDK)
- **정보원**: DART API, Fed 홈페이지, SEC EDGAR, Trump X 스크래퍼
- **주가 데이터**: yfinance, KIS Open API
- **스케줄러**: APScheduler (15-30분 간격)
- **대시보드**: Streamlit (localhost:8501)
- **테스트**: pytest

## 시작하기

### 1. 환경 설정
```bash
cd ~/Desktop/FTTS
pip install -r requirements.txt
cp .env.example .env
# .env 파일에 API 키 입력 (ANTHROPIC_API_KEY, DART_API_KEY 등)
```

### 2. DB 초기화
```bash
python main.py init-db
```

### 3. 스케줄러 실행 (자동 수집 + 분석)
```bash
python main.py scheduler --interval 20
```
- 20분 간격으로 모든 정보원에서 데이터 수집 → 이벤트 추출 → 인과관계 연결
- Ctrl+C로 중지

### 4. 대시보드 실행
```bash
python main.py dashboard
```
- http://localhost:8501 에서 실시간 모니터링
- 이벤트, 정보원, 매매, 인과관계 그래프 조회

### 2. DB 초기화
```bash
python -m database.db_manager --init
```

### 3. 모의 투자 실행
```bash
python -m trading.paper_trader --run
```

### 4. 대시보드 실행
```bash
streamlit run monitoring/dashboard.py
```

## 폴더 구조

```
~/Desktop/FTTS/
├── CLAUDE.md              # 프로젝트 규칙 (Claude Code가 자동으로 읽음)
├── README.md              # 이 파일
├── requirements.txt       # Python 의존성
├── .env.example           # 환경 변수 예시
├── .gitignore             # Git 제외 설정
│
├── config/                # 설정
├── data/                  # 데이터 (raw, processed, backtest)
├── database/              # DB 모델 및 스키마
├── core/                  # 핵심 로직 (인과관계, 가중치, Self-Feedback)
├── data_collection/       # 데이터 수집 (뉴스, 블로그, 주가)
├── nlp/                   # 자연어 처리 (이벤트 추출, 감성 분석)
├── trading/               # 매매 (모의, 실전, 리스크 관리)
├── backtest/              # 백테스트 (버핏 블라인드 테스트)
├── monitoring/            # 모니터링 (대시보드, 정확도 추적)
└── tests/                 # 테스트
```

## 현재 상태

- **Phase**: 1 (기반 구축)
- **다음 작업**: requirements.txt 작성 → schema.sql 생성 → SQLAlchemy 모델 정의

## 주의사항

- **live_trader.py는 정확도 80% 확인 후에만 실행**
- .env 파일은 절대 git에 커밋하지 말 것
- API 키는 .env.example에 예시로만 표시하고, 실제 키는 .env에만 저장

## 참고 자료

- 메르 블로그: https://blog.naver.com/ranto28
- KIS Open API: https://apiportal.koreainvestment.com
- NetworkX: https://networkx.org/documentation
