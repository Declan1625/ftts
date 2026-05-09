# 메르 블로그 전체 크롤링 + 메르식 분석 워크플로우

## 목적

메르 블로그(ranto28)의 **과거 글 전체**를 수집하여 메르식 투자법의 핵심인 **"사건 → 정보원 → 인과관계"** 데이터를 추출하는 독립형 n8n 워크플로우.

## 아키텍처

```
[Manual Trigger]
       ↓
[Set Max Pages] (최대 50페이지 설정)
       ↓
[Loop Pages] (페이지 1~50 생성)
       ↓
[Fetch Post List] (/blog/fetch) (페이지별 포스트 번호)
       ↓
[Split Post Numbers] (개별 post_no로 분리)
       ↓
[Analyze Post] (/blog/analyze) (메르식 분석)
       ↓
[Aggregate Results] (결과 취합)
       ↓
[Save to File] (JSONL로 저장)
       ↓
[Discord Notification] (완료 알림)
```

## FTTS API 엔드포인트

### 1. GET /blog/fetch?page=N
페이지별 포스트 번호 목록 반환

**응답:**
```json
{
  "page": 1,
  "post_nos": ["224232522491", "224209123456", ...]
}
```

### 2. POST /blog/analyze
포스트 메르식 분석

**요청:**
```json
{
  "post_no": "224232522491"
}
```

**응답:**
```json
{
  "post_no": "224232522491",
  "title": "글 제목",
  "published_at": "2026-05-09T05:04:55.296913",
  "events": ["사건1", "사건2"],
  "primary_source": "FT",
  "reference_sources": ["WSJ", "Reuters"],
  "source_correlations": [
    {"from": "FT", "to": "WSJ", "relation": "confirm", "weight": 0.9}
  ],
  "affected_industries": ["반도체", "에너지"],
  "affected_companies": ["Samsung", "SK Hynix"],
  "causal_chain": "X 사건 → 반도체 산업 호황 → KOSPI 상승",
  "confidence": 0.85,
  "summary": "글의 핵심 요약"
}
```

## 사용법

### Step 1: 워크플로우 import
n8n 대시보드에서 `config/n8n_mer_crawl_workflow.json`을 import.

### Step 2: 환경변수 설정 (선택)
n8n 환경변수:
- `FTTS_API_URL`: FTTS API 베이스 URL (기본값: `http://localhost:8000`)
- `DISCORD_WEBHOOK_URL`: Discord 알림용 웹훅

### Step 3: Manual Trigger로 실행
"Execute Workflow" 클릭 → 크롤링 시작

## 결과 저장

크롤링 완료 후 결과는 **JSONL 형식**으로 저장됨:
- 파일명: `mer_analysis_YYYYMMDD_HHmmss.jsonl`
- 위치: FTTS 프로젝트 root (또는 n8n 설정된 경로)
- 한 줄 = 1개 포스트의 분석 결과

### 예시:
```jsonl
{"post_no":"224232522491","title":"...","events":[],"primary_source":"Unknown",...}
{"post_no":"224209123456","title":"...","events":["반도체 수급 위기"],"primary_source":"FT",...}
```

## 성능 고려사항

- **페이지당 포스트**: 30개
- **최대 페이지**: 50 (1,500개 글)
- **요청 간격**: 블로그 스크래퍼가 1초 간격 유지
- **분석 시간**: 포스트당 ~2-3초 (Claude API)
- **예상 전체 소요 시간**: 50-75분

## 주의사항

1. **API 키**: Claude API 인증이 필요 (`.env` 파일의 `ANTHROPIC_API_KEY`)
2. **블로그 스크래퍼**: 메르 블로그의 HTML 구조 변경 시 업데이트 필요
3. **Rate Limiting**: 네이버 블로그 서버 부하 방지 위해 요청 간격 유지

## 데이터 활용

수집된 분석 결과는 나중에:
1. **Event 테이블에 저장**: 실제 시장 이벤트 리뷰
2. **Source Correlations 분석**: 정보원 간 신뢰도 관계 학습
3. **Causal Graph 강화**: 사건 → 산업 → 주가의 인과관계 구축
