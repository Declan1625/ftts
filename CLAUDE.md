# FTTS: 인과관계 기반 주식 AI

**목적**: 시장 사건 → 산업 → 기업 인과관계 분석 + 자가 학습 투자 AI

## Phase 현황

| Phase | 상태 | 내용 |
|-------|------|------|
| 1-4 | ✅ 완료 | 기반/수집/엔진/모의투자 |
| 5 | 🔄 진행 | n8n 워크플로 (RSS→분석→Discord) |
| 6 | 🔄 진행 | KIS API 연동 + 모의투자 자동화 |

## Phase 6 진행 현황

**1순위: ✅ KIS API + REST API 완료** (2026-05-09)
- KIS 클라이언트 (국내+해외 듀얼)
- FastAPI REST API (5 endpoints)
- 모의투자 파이프라인 자동화
- n8n 워크플로우 설정 완료

**2순위: ✅ Render 배포 완료** (2026-05-09)
- FastAPI를 Render에 배포 (https://ftts.onrender.com)
- SQLite 데이터베이스 연동
- Discord 웹훅 알림 활성화
- n8n 워크플로우 연동 (RSS → API → Discord)
- **첫 실행 테스트 완료**: Discord 메시지 수신 확인

**3순위: 🔄 정확도 80% 달성** (진행 중)
- n8n 워크플로우: 메르/DART/RSS 3개 흐름 한 페이지 통합 완료
- DART API 키 발급 완료, bgn_de=20260101 파라미터 추가 필요 (n8n 수동)
- RSS: Render 슬립 이슈로 테스트 대기 중
- accuracy_tracker predictions 누적 여부 미확인
- weight_engine 튜닝 (BUY_THRESHOLD, SELL_THRESHOLD)
- **예상**: 1-2주 (실제 시장 데이터 누적)

**다음 할 일**
1. n8n DART 노드에 `bgn_de=20260101` 수동 추가 → 테스트
2. Render 깨우고 RSS 테스트
3. accuracy_tracker 확인 (predictions 쌓이는지)

**4순위: ⏳ KIS 실전 모드** (80% 달성 후)
- 80% 달성 후 실전 활성화
- live_trader 운영 (금지 조건 해제)
- 실전 거래 시작

## 핵심 모듈

`core/`: causal_graph, weight_engine, self_feedback, source_grader
`trading/`: paper_trader, live_trader (금지)
`monitoring/`: accuracy_tracker, alert_manager
`backtest/`: buffett_simulator

## 규칙

- 한 번에 하나의 모듈만
- 새 함수 = 테스트 필수
- 하드코딩 금지 (config/settings.py)
- live_trader는 정확도 80% 전까지 실행 금지

## 클로드 협업 규칙

**상태 정리 (`123123123` 단축명령)**
- 결정된 것 / 미결정된 것 / 다음 할 일을 구분해서 정리
- 결정된 내용은 메모리에 저장 (user/feedback/project/reference)
- 변경사항을 CLAUDE.md에 반영

**코딩 원칙**
- 토큰 효율: 불필요한 주석/로그/변수명 최소화
- 간결함: 동작하는 최소 단위 코드 작성
- 재사용: 기존 함수/패턴 활용 (중복 제거)

## 토큰 감시 규칙 (CEO + 전 에이전트 필수 준수)

### 파일 읽기 — 반드시 이 순서
1. `grep -n "키워드" 파일` → 관련 라인 번호 확인
2. `Read(file, offset=시작줄, limit=필요줄수)` → 해당 섹션만
3. 전체 Read는 파일이 **60줄 이하**일 때만 허용

### CEO(메인 클로드) 에이전트 투입 전 의무
- 에이전트 투입 전 CEO가 grep으로 관련 라인 미리 수집
- 에이전트 프롬프트에 **현재 코드 스니펫 직접 삽입** (에이전트가 Read 안 해도 되게)
- 수정 지시는 `old_string → new_string` 형식으로 정확히 명시

### 에이전트 보고 형식 (짧게)
- 변경된 파일명 + 라인 번호 요약만
- 코드 전체 출력 금지
- "검토 결과: 이상 없음" 한 줄로 끝낼 것

### 금지 행동
- 파일 전체 Read 후 일부만 사용
- `cat` 으로 파일 출력
- 이미 프롬프트에 있는 코드를 다시 Read
- diff 전체 출력 (--stat 으로 요약만)

### git 검증
- `git diff --stat` 으로 변경 파일 수/줄 수 확인 (전체 diff 출력 금지)
- 문법 검사: `python3 -c "import ast; ast.parse(open('파일').read())"` 한 줄로
