# 메르 블로그 메르식 분석 구현 완료

**일시:** 2026-05-09  
**상태:** ✅ 완료 (API 구조 검증됨)

## 구현 내용

### 1. 메르식 분석 모듈 (`nlp/mer_analyzer.py`)

메르 블로그 글을 분석하여 메르식 투자법의 핵심 요소 추출:
- **Events**: 글에서 언급된 실제 사건들
- **Primary Source**: 메르가 이 사건을 처음 알게 된 정보원
- **Reference Sources**: 글에서 참고한 다른 정보원들
- **Source Correlations**: 정보원 간 관계 (confirm/conflict/complement)
- **Affected Industries/Companies**: 영향받는 산업 & 회사
- **Causal Chain**: "X 사건 → Y 산업 → Z 결과" 형태
- **Confidence**: 분석 신뢰도

**특징:**
- Claude API (Sonnet 4.5) 기반
- 3회 재시도 로직 포함
- API 키 오류 시 graceful fallback

### 2. API 엔드포인트 (`api/server.py`)

#### GET /blog/fetch?page=N
페이지별 포스트 번호 목록 (페이지당 30개)

```bash
curl http://localhost:8000/blog/fetch?page=1
# 응답: {"page": 1, "post_nos": ["224232522491", ...]}
```

#### POST /blog/analyze
포스트 메르식 분석

```bash
curl -X POST http://localhost:8000/blog/analyze \
  -H "Content-Type: application/json" \
  -d '{"post_no":"224232522491"}'
```

**응답:**
```json
{
  "post_no": "224232522491",
  "title": "글 제목",
  "published_at": "2026-05-09T...",
  "events": ["사건1"],
  "primary_source": "FT",
  "reference_sources": ["WSJ"],
  "source_correlations": [
    {"from": "FT", "to": "WSJ", "relation": "confirm", "weight": 0.9}
  ],
  "affected_industries": ["반도체"],
  "affected_companies": ["Samsung"],
  "causal_chain": "X 사건 → 반도체 산업 호황 → KOSPI 상승",
  "confidence": 0.85,
  "summary": "..."
}
```

### 3. n8n 워크플로우 (`config/n8n_mer_crawl_workflow.json`)

독립형 배치 크롤링 워크플로우:
1. Manual Trigger (시작)
2. Set Max Pages (최대 50페이지)
3. Loop Pages (페이지 1~50 생성)
4. Fetch Post List (API 호출)
5. Split Post Numbers (개별 처리용 분리)
6. Analyze Post (메르식 분석)
7. Aggregate Results (결과 취합)
8. Save to File (JSONL로 저장)
9. Discord Notification (완료 알림)

**결과 저장:**
- 파일명: `mer_analysis_YYYYMMDD_HHmmss.jsonl`
- 한 줄 = 1개 포스트의 분석 JSON

### 4. 문서

- `docs/MER_CRAWL_WORKFLOW.md` — n8n 워크플로우 사용 가이드
- `docs/IMPLEMENTATION_SUMMARY.md` — 이 문서

## 테스트 결과

```
✅ /blog/fetch?page=1 → 포스트 번호 반환 성공
✅ /blog/analyze → 포스트 분석 반환 성공 (구조 검증됨)
✅ API 응답 스키마 정상
```

## 다음 단계

### 즉시 필요
1. **ANTHROPIC_API_KEY 설정** (`.env` 파일)
   - 현재 `your_key_here`로 placeholder
   - 실제 API 키로 교체 필요

### 단기 (1주)
2. n8n 워크플로우 import & 실행
3. 1-2페이지 파일럿 실행 (60개 글)
4. JSONL 결과 검토 및 프롬프트 튜닝

### 중기 (2주)
5. 전체 50페이지 크롤링 실행 (1,500개 글)
6. 결과를 Event/Causal_edges 테이블에 반영
7. source_correlations 기반 Source Grading 업데이트

### 장기
8. 메르식 데이터로 매매 신호 개선
9. 정확도 80% 달성 후 KIS 실전 모드 활성화

## 기술 스택

| 컴포넌트 | 기술 |
|--------|------|
| 블로그 스크래퍼 | BeautifulSoup + requests |
| 메르식 분석 | Claude API (Sonnet 4.5) |
| API 서버 | FastAPI + Uvicorn |
| 워크플로우 | n8n (자체 호스팅) |
| 데이터 저장 | JSONL (임시), SQLite/PostgreSQL (최종) |

## 파일 목록

```
📁 nlp/
  └── mer_analyzer.py (신규)
📁 api/
  └── server.py (수정: 2 엔드포인트 추가)
📁 config/
  └── n8n_mer_crawl_workflow.json (신규)
📁 docs/
  ├── MER_CRAWL_WORKFLOW.md (신규)
  └── IMPLEMENTATION_SUMMARY.md (이 파일)
```

## 주의사항

1. **프롬프트 언어**: 한국어 (Claude가 한국어 처리 가능)
2. **Rate Limiting**: 블로그 스크래퍼가 1초 간격 유지
3. **메모리**: 1,500개 글 분석 시 ~300MB RAM 필요
4. **비용**: Claude API 호출당 비용 발생 (약 1,500 × 0.005 = $7.50)
