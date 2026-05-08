# FTTS: 인과관계 기반 주식 AI

**목적**: 시장 사건 → 산업 → 기업 인과관계 분석 + 자가 학습 투자 AI

## Phase 현황

| Phase | 상태 | 내용 |
|-------|------|------|
| 1-4 | ✅ 완료 | 기반/수집/엔진/모의투자 |
| 5 | 🔄 진행 | n8n 워크플로 (RSS→분석→Discord) |
| 6 | ⏳ 예정 | 정확도 리포트→텔레그램→실전 |

## Phase 6 목표

**정확도 80% 달성** (수익률 아님, 투자목표 달성율)
- 1순위: accuracy_tracker.py 개선 (목표달성율 측정)
- 2순위: 텔레그램 알림 (실시간 신호)
- 3순위: weight_engine 튜닝

**KIS API는 나중에**: yfinance로 모의→실전 검증 후 연동

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
