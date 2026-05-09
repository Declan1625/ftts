# KIS API + 모의투자 구현 체크리스트

**완료 날짜**: 2026-05-09  
**최종 상태**: REST API 기반 시스템 완성

---

## ✅ 완료된 항목

### 1. KIS API 클라이언트
- [x] `data/kis_api.py` - 토큰 발급, 주가 조회, 계좌 정보
- [x] 국내(KR) + 해외(US) 듀얼 시장 지원
- [x] OAuth 토큰 관리, 자동 갱신
- [x] 모의투자/실전 구분 (현재 모의투자만 활성)

### 2. 실시간 가격 수집
- [x] `data/price_fetcher.py` - KIS API → DB 저장
- [x] 배치 조회 및 에러 처리
- [x] 중복 검사 (같은 날짜 중복 방지)

### 3. 모의투자 파이프라인
- [x] `trading/paper_trading_pipeline.py` - 일일 자동화 엔진
- [x] 신호 생성 (weight_engine) → 매매 실행 (paper_trader)
- [x] Outcome 자동 평가 (N일 뒤 정확도 측정)
- [x] DB 인과관계 그래프 로드

### 4. REST API 서버
- [x] `api/paper_trading_api.py` - FastAPI 기반
- [x] 5개 엔드포인트 구현:
  - `POST /api/paper-trading/run` — 모의투자 실행
  - `GET /api/accuracy/report` — 정확도 리포트
  - `GET /api/positions/current` — 현재 포지션
  - `GET /api/paper-trading/status` — 상태 조회
  - `GET /api/health` — 헬스 체크

### 5. 테스트 인프라
- [x] `scripts/run_paper_trading.py` — CLI 실행 도구
- [x] `scripts/setup_sample_data.py` — 샘플 데이터 생성
- [x] 샘플 데이터 기본 구성:
  - 기업 5개, 소스 3개, 이벤트 40개
  - 인과관계 엣지 80개, 주가 25개

### 6. 설정 및 문서
- [x] `.env` - 국내/해외 KIS 크레덴셜 설정
- [x] `docs/N8N_WORKFLOW.md` - n8n 자동화 가이드
- [x] `render_deploy.sh` - Render 배포 스크립트
- [x] API 구조 설계 완료

---

## 🔄 다음 단계 (우선순위)

### 1. Render 배포 (1-2시간)
```bash
# 1. Git push
git add -A
git commit -m "Add KIS API and REST API endpoints"
git push origin main

# 2. Render 웹 대시보드에서 수동 설정:
#    - New Web Service 생성
#    - GitHub repo 연결
#    - Start Command: uvicorn api.paper_trading_api:app --host 0.0.0.0 --port 10000
#    - Environment Variables 추가 (KIS_APP_KEY_KR, KIS_APP_SECRET_KR, KIS_ACCOUNT_NO_KR 등)
```

### 2. n8n 워크플로우 구성 (30분)
```
참고: docs/N8N_WORKFLOW.md
- Cron Trigger (매일 09:00)
- HTTP POST /api/paper-trading/run
- Discord Webhook 알림
```

### 3. 정확도 향상 (지속적)
- 현재: 샘플 데이터로 테스트 중
- 목표: 실제 이벤트 데이터로 80% 달성
- 방법: weight_engine 임계값 조정, 신뢰도 필터링

### 4. KIS 실전 모드 (80% 달성 후)
```python
# 현재: KISClient(mock=True) — 모의투자
# 미래: KISClient(mock=False) — 실전 매매
# 조건: AccuracyTracker.can_go_live() == True (80% 이상)
```

---

## 📊 시스템 아키텍처

```
┌─────────────────────────────────────────┐
│          n8n 스케줄러                   │
│   [Cron 09:00] → [HTTP POST]            │
└──────────────┬──────────────────────────┘
               │
        POST /api/paper-trading/run
               │
┌──────────────▼──────────────────────────┐
│      Render (Python FastAPI)            │
│                                         │
│  ┌─ paper_trading_api.py                │
│  ├─ paper_trading_pipeline.py           │
│  ├─ weight_engine.py                    │
│  └─ paper_trader.py                     │
└──────────────┬──────────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
[Database]  [KIS API]  [Discord]
[PostgreSQL] [실시간    [알림]
[모의투자]   가격]
```

---

## 🧪 테스트 명령어

**로컬 테스트:**
```bash
# 1. 샘플 데이터 생성
python -m scripts.setup_sample_data --clean

# 2. 모의투자 CLI 실행 (테스트 모드)
python -m scripts.run_paper_trading --test

# 3. API 직접 호출 (테스트)
python -m api.paper_trading_api  # Uvicorn 시작

# 4. curl로 API 테스트
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/paper-trading/run \
  -H "Content-Type: application/json" \
  -d '{"market": "KR", "dry_run": false}'
```

**정확도 리포트:**
```bash
python -m scripts.run_paper_trading --report
python -m scripts.run_paper_trading --report --days 30
```

---

## 🔑 환경 변수 정리

| 변수 | 용도 | 필수 | 값 |
|------|------|------|-----|
| `DATABASE_URL` | DB 연결 | ⭐⭐⭐ | `postgresql://...` |
| `KIS_APP_KEY_KR` | 국내 API 키 | ⭐⭐⭐ | (발급받은 값) |
| `KIS_APP_SECRET_KR` | 국내 API 시크릿 | ⭐⭐⭐ | (발급받은 값) |
| `KIS_ACCOUNT_NO_KR` | 국내 계좌번호 | ⭐⭐⭐ | `12345678-01` |
| `KIS_APP_KEY_US` | 해외 API 키 | ⭐⭐⭐ | (발급받은 값) |
| `KIS_APP_SECRET_US` | 해외 API 시크릿 | ⭐⭐⭐ | (발급받은 값) |
| `KIS_ACCOUNT_NO_US` | 해외 계좌번호 | ⭐⭐⭐ | `12345678-02` |
| `ANTHROPIC_API_KEY` | Claude API | ⭐⭐ | (선택) |
| `GOOGLE_API_KEY` | Gemini API | ⭐⭐ | (선택) |
| `DISCORD_WEBHOOK_URL` | Discord 알림 | ⭐⭐ | (n8n용) |

---

## 📈 성능 지표 (현재)

| 항목 | 값 | 비고 |
|------|-----|------|
| 정확도 | 0% | 샘플 데이터 (아직 평가 없음) |
| 포트폴리오 | ₩10,000,000 | 초기 현금 |
| 활성 기업 | 5개 | 테스트 데이터 |
| 일일 신호 | ~5-10개 | 샘플 데이터 기준 |
| API 응답 시간 | <1초 | 로컬 테스트 |

---

## 🚨 알려진 제약사항

1. **KIS API 네트워크 연결 필요**
   - 로컬 테스트 시 DNS 오류 발생 가능
   - Render 배포 후 정상 작동

2. **모의투자 전용**
   - 실전 매매는 `accuracy >= 80%` 이후 활성화
   - 현재 `KISClient(mock=True)` 고정

3. **Database**
   - 로컬: SQLite (`ftts.db`)
   - Render: PostgreSQL (별도 설정)

4. **Outcome 평가 지연**
   - 결정 후 5일 뒤 자동 평가
   - 정확도 누적에 시간 필요

---

## 💡 최적화 제안

### 단기 (1주)
- [x] REST API 기본 구현 완료
- [ ] Render 배포 완료
- [ ] n8n 자동화 설정 완료

### 중기 (2-4주)
- [ ] 실제 이벤트 데이터 수집 (n8n RSS)
- [ ] weight_engine 임계값 튜닝
- [ ] 정확도 60% 달성 목표

### 장기 (1-3개월)
- [ ] 정확도 80% 달성
- [ ] KIS 실전 모드 활성화
- [ ] 텔레그램 알림 추가
- [ ] 실시간 대시보드 (Streamlit)

---

## 📞 문제 해결

**Q: Render 배포 후 API 호출 시 500 error**  
A: 환경 변수 확인, Render 로그에서 오류 메시지 확인

**Q: n8n에서 HTTP 요청이 timeout**  
A: Render 서버가 절전 모드일 수 있음, Pro 계획 권장

**Q: 신호가 생성되지 않음**  
A: 이벤트 데이터 확인, sentiment 필드 값 확인

---

**최종 상태**: 🟢 준비 완료 (Render 배포만 남음)
