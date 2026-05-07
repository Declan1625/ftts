# n8n 888 Claude AI 분석 프롬프트

## 🎯 사용 목적
n8n 워크플로 내부에서 Claude API를 호출하여 뉴스/블로그 텍스트를 분석

## 📋 프롬프트 정보

**모델:** claude-opus-4-1-20250805  
**API 키:** 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

---

## 🔥 System Prompt

```
당신은 금융·경제 뉴스 분석 전문가입니다.
주어진 텍스트에서 투자 관련 이벤트를 JSON 형식으로 추출하고 분석합니다.

응답 형식: 다음 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{
  "events": [
    {
      "event_type": "policy|earnings|acquisition|bankruptcy|product_launch|lawsuit|regulation|other",
      "summary": "한 문장 요약 (한글)",
      "affected_industries": ["산업명1", "산업명2"],
      "affected_companies": ["회사명1", "회사명2"],
      "sentiment": 0.8,
      "confidence": 0.9
    }
  ],
  "overall_sentiment": 0.75,
  "market_impact": "긍정적|부정적|중립",
  "key_takeaway": "투자자 관점의 핵심 요약"
}

주의:
- JSON 형식만 출력 (마크다운 블록 금지)
- event_type은 위 값 중 하나만 사용
- sentiment: -1.0 ~ 1.0 (음수=부정, 양수=긍정)
- confidence: 0.0 ~ 1.0 (신뢰도)
- 이벤트 없으면 빈 배열 []
- 모든 응답은 유효한 JSON이어야 함
```

---

## 🔨 User Prompt Template

n8n의 "Call Claude" 노드에서 다음과 같이 설정:

```json
{
  "model": "claude-opus-4-1-20250805",
  "max_tokens": 2048,
  "messages": [
    {
      "role": "user",
      "content": "다음 텍스트를 분석해주세요:\n\n제목: {{ $json.title }}\n출처: {{ $json.source_name }}\nURL: {{ $json.url }}\n\n본문:\n{{ $json.text }}"
    }
  ]
}
```

또는 간단하게:

```
다음 금융·경제 뉴스를 분석하고 투자 이벤트를 추출해주세요:

제목: {{ $json.title }}
출처: {{ $json.source_name }}

{{ $json.text }}
```

---

## 📊 응답 예시

```json
{
  "events": [
    {
      "event_type": "policy",
      "summary": "미국 상무부, 반도체 수출 규제 강화로 한국 메모리칩 업계 영향",
      "affected_industries": ["반도체", "전자"],
      "affected_companies": ["SK하이닉스", "삼성전자"],
      "sentiment": -0.7,
      "confidence": 0.95
    }
  ],
  "overall_sentiment": -0.7,
  "market_impact": "부정적",
  "key_takeaway": "메모리칩 기업들의 매출 감소 전망, 단기 매도 신호"
}
```

---

## 🔗 n8n 통합 방법

### 옵션 1: OpenAI Node (권장)
1. n8n에서 "OpenAI" 노드 추가
2. 설정:
   - Provider: Custom (OpenAI-compatible)
   - API Key: `sk-ant-api03-f6lbN...`
   - Base URL: `https://api.anthropic.com/v1`
   - Model: `claude-opus-4-1-20250805`
   - Max Tokens: `2048`

### 옵션 2: HTTP Request Node (더 직접적)
```
Method: POST
URL: https://api.anthropic.com/v1/messages
Headers:
  Content-Type: application/json
  x-api-key: sk-ant-api03-f6lbN...
  anthropic-version: 2023-06-01

Body:
{
  "model": "claude-opus-4-1-20250805",
  "max_tokens": 2048,
  "system": "[위의 System Prompt]",
  "messages": [
    {
      "role": "user",
      "content": "{{ $json.text }}"
    }
  ]
}
```

---

## ✅ 워크플로 순서

```
RSS 피드 → HTML 추출 → 텍스트 추출 → Claude AI 분석 → 결과 매핑 → Discord 발송
```

---

## 📝 n8n 888 워크플로 체크리스트

- [ ] Claude API 노드 추가 (OpenAI 또는 HTTP Request)
- [ ] 시스템 프롬프트 설정
- [ ] 입력값 매핑 (title, source_name, text 등)
- [ ] 출력값 파싱 (events 배열 추출)
- [ ] FTTS API 또는 Discord 노드 연결
- [ ] 테스트 실행

---

## 🎯 다음 단계

이 프롬프트를 n8n 888의 Claude AI 노드에 설정한 후:
1. "Execute Workflow" 클릭
2. 응답 확인 (JSON 형식)
3. Discord에 결과 발송

준비 완료! 🚀
