# n8n 워크플로우 설정 가이드

## 📋 목표
매일 09:00에 모의투자 파이프라인을 자동 실행하고, 결과를 Discord로 알림

```
[Cron Trigger: 09:00] 
         ↓
[HTTP Request: POST /api/paper-trading/run]
         ↓
[Discord Webhook: 결과 알림]
```

---

## 🚀 n8n 노드 구성

### 1️⃣ Cron Trigger (시간 설정)

**노드 유형**: `Trigger → Cron`

**설정:**
- **Cron Expression**: `0 9 * * *` (매일 09:00)
- **Timezone**: Asia/Seoul

---

### 2️⃣ HTTP Request (API 호출)

**노드 유형**: `HTTP Request`

**설정:**

| 항목 | 값 |
|------|-----|
| **Method** | POST |
| **URL** | `https://ftts.onrender.com/api/paper-trading/run` |
| **Authentication** | None (공개 엔드포인트) |
| **Body** | JSON |

**Body JSON:**
```json
{
  "market": "KR",
  "dry_run": false
}
```

**요청 헤더:**
```json
{
  "Content-Type": "application/json"
}
```

---

### 3️⃣ Discord Webhook (알림)

**노드 유형**: `Discord`

**설정:**

| 항목 | 값 |
|------|-----|
| **Webhook URL** | `https://discord.com/api/webhooks/...` (기존 웹훅) |
| **Message** | 아래 참고 |

**메시지 템플릿 (JavaScript):**

```javascript
const response = {{$node["HTTP Request"].json}};

let color = response.success ? 3066993 : 15158332; // 초록 또는 빨강
let status = response.success ? "✅ 성공" : "❌ 실패";

{
  "embeds": [
    {
      "title": "📊 모의투자 일일 실행",
      "color": color,
      "fields": [
        {
          "name": "상태",
          "value": status,
          "inline": true
        },
        {
          "name": "시장",
          "value": response.market === "KR" ? "🇰🇷 국내" : "🇺🇸 해외",
          "inline": true
        },
        {
          "name": "처리 기업",
          "value": response.companies_processed.toString(),
          "inline": true
        },
        {
          "name": "신호 생성",
          "value": response.signals_generated.toString(),
          "inline": true
        },
        {
          "name": "매매 체결",
          "value": response.trades_executed.toString(),
          "inline": true
        },
        {
          "name": "결정 평가",
          "value": response.outcomes_evaluated.toString(),
          "inline": true
        },
        {
          "name": "포트폴리오 가치",
          "value": `₩${response.portfolio_value?.toLocaleString() || 'N/A'}`,
          "inline": false
        },
        {
          "name": "총 수익률",
          "value": `${(response.total_return * 100)?.toFixed(2) || 0}%`,
          "inline": false
        }
      ],
      "timestamp": new Date().toISOString()
    }
  ]
}
```

---

## 🔄 워크플로우 흐름

### 성공 케이스 (Success)
```
Cron (09:00)
    ↓
HTTP Request (200 OK)
    ↓
파이프라인 실행
    ↓
Discord: ✅ 메시지 (초록)
    ↓
Complete
```

### 실패 케이스 (Error Handling)

HTTP Request 노드 → **If** → 조건 분기:

**조건 1: 성공 (statusCode === 200)**
- Discord 초록 메시지

**조건 2: 실패 (statusCode !== 200)**
- Discord 빨강 메시지 + 에러 로그

**JavaScript:**
```javascript
return {{$node["HTTP Request"].json}};
```

---

## 🛠️ 설정 체크리스트

- [ ] Render에 FastAPI 배포됨
- [ ] API 엔드포인트 정상 작동 (`/api/health`)
- [ ] Discord 웹훅 URL 확인
- [ ] n8n에 크론 설정 (`0 9 * * *`)
- [ ] HTTP 요청 테스트 (수동 실행)
- [ ] Discord 메시지 포맷 확인

---

## 📝 추가 옵션

### 정확도 리포트 일주일마다 (선택)

**Cron**: `0 9 * * 1` (매주 월요일 09:00)

**HTTP Request**:
```
GET https://ftts.onrender.com/api/accuracy/report?days=7
```

**Discord 메시지**:
```javascript
const report = {{$node["HTTP Request"].json}};

{
  "embeds": [
    {
      "title": "📈 주간 정확도 리포트",
      "fields": [
        {
          "name": "정확도",
          "value": `${(report.accuracy * 100).toFixed(1)}%`
        },
        {
          "name": "평가 건수",
          "value": `${report.correct}/${report.total_evaluated}`
        },
        {
          "name": "메르식 (사건분석)",
          "value": report.mercer_accuracy ? `${(report.mercer_accuracy * 100).toFixed(1)}%` : "N/A"
        },
        {
          "name": "버핏식 (투자신호)",
          "value": report.buffett_accuracy ? `${(report.buffett_accuracy * 100).toFixed(1)}%` : "N/A"
        },
        {
          "name": "실전 전환 여부",
          "value": report.live_gate_passed ? "✅ 가능" : "⏳ 진행 중"
        }
      ]
    }
  ]
}
```

---

## 🐛 트러블슈팅

### 문제: "Connection timeout"
→ Render 서버가 절전 모드일 수 있음
→ 해결: Render 계획을 Pro로 업그레이드하거나, 주기적으로 핑 보내기

### 문제: "Authentication failed"
→ Discord 웹훅 URL이 잘못됐거나 만료됨
→ 해결: 새 웹훅 생성

### 문제: "API returns 500 error"
→ DB 연결 문제 또는 KIS 인증 실패
→ 해결: Render 로그 확인, KIS 토큰 갱신

---

## 📞 모니터링

n8n 대시보드에서:
- **Executions** 탭: 일일 실행 기록
- **Logs** 탭: 각 노드의 입출력 확인
- **Active Workflows** 탭: 활성화 상태 확인

Discord에서:
- 매일 결과 알림 받기
- 실패 시 즉시 알림
