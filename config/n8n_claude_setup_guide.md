# n8n 888 Claude AI 노드 설정 완벽 가이드

## 🎯 목표
n8n 워크플로 중간에 Claude AI 노드를 삽입하여 텍스트 분석

## 📍 현재 워크플로 구조
```
RSS → HTML 추출 → 텍스트 추출 → [🆕 Claude AI] → Discord 발송
```

---

## 📝 Step 1: n8n 웹 UI 접속

1. 브라우저에서 `http://localhost:5678` 접속
2. 현재 워크플로 "FTTS" 열기
3. 편집 모드 진입

---

## ➕ Step 2: Claude AI 노드 추가

### 2-1. 노드 추가 위치
- **"블로그 텍스트 추출" 노드** (HTML 콘텐츠 처리 후)와 
- **"FTTS 워짓" 노드** (아직 설정 안 된) 사이에 추가

### 2-2. 노드 추가 방법

1. **"블로그 텍스트 추출" 노드의 오른쪽 끝**에 있는 `+` 버튼 클릭
   ```
   블로그 텍스트 추출 —— (+) ——
   ```

2. 팝업 메뉴에서 **"Add node"** 또는 **"+"** 선택

3. **검색창에 "OpenAI" 입력**
   ```
   🔍 "OpenAI" 검색
   ```

4. **"OpenAI" 노드 클릭** (또는 "Anthropic" 있으면 그것)
   - 없으면 **"HTTP Request"** 선택 (Step 3-B 참고)

---

## ⚙️ Step 3: Claude API 설정 (2가지 방법)

### 🟢 방법 A: OpenAI Node (권장)

#### 3A-1. 노드 이름 변경
1. 추가된 노드 클릭
2. 좌측 상단 노드명 클릭 (기본: "OpenAI")
3. **"Claude AI 분석"** 으로 변경
4. Enter 키 눌러 저장

#### 3A-2. 우측 패널 설정
노드를 클릭하면 우측에 설정 패널이 열립니다.

**[Authentication]**
1. **"Create new credential"** 클릭
2. **Credential name**: `Claude API`
3. **API Key**: 다음 키를 복사해서 붙여넣기
   ```
   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
   ```
4. **"Save"** 클릭

**[Base URL]** (중요!)
- 기본값 대신 다음으로 변경:
  ```
  https://api.anthropic.com/v1
  ```

**[Model]**
- 드롭다운에서 모델 선택 또는 직접 입력:
  ```
  claude-opus-4-1-20250805
  ```

**[Max Tokens]**
- `2048` 입력

**[System Prompt]**
- 다음을 복사해서 붙여넣기:
  ```
  당신은 금융·경제 뉴스 분석 전문가입니다.
  주어진 텍스트에서 투자 관련 이벤트를 JSON 형식으로 추출하고 분석합니다.

  응답 형식: 다음 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

  {
    "events": [
      {
        "event_type": "policy|earnings|acquisition|bankruptcy|product_launch|lawsuit|regulation|other",
        "summary": "한 문장 요약 (한글)",
        "affected_industries": ["산업명1"],
        "affected_companies": ["회사명1"],
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
  - sentiment: -1.0 ~ 1.0
  - 이벤트 없으면 빈 배열 []
  ```

**[Messages]**
1. **Add message** 클릭
2. **Role**: `user`
3. **Content** (다음을 복사):
   ```
   제목: {{ $json.title }}
   출처: {{ $json.source_name }}

   본문:
   {{ $json.text }}

   위 텍스트를 분석하고 투자 이벤트를 JSON으로 추출해주세요.
   ```

#### 3A-3. 결과 매핑 (JSON 파싱)
1. **"Claude AI 분석" 노드** 다음에 **"JSON 파싱" 노드** 추가 (선택사항)
2. 또는 그 다음 노드에서 응답 처리

---

### 🔵 방법 B: HTTP Request Node (OpenAI 없을 때)

#### 3B-1. 노드 추가
1. `+` 버튼 → **"HTTP Request"** 검색 및 선택
2. 노드명: **"Claude API 호출"** 로 변경

#### 3B-2. 설정 패널

**[Method]**
- `POST`

**[URL]**
```
https://api.anthropic.com/v1/messages
```

**[Authentication]**
- `None`

**[Headers]**
우측 "+" 클릭해서 추가:

| Key | Value |
|-----|-------|
| Content-Type | application/json |
| x-api-key | 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 |
| anthropic-version | 2023-06-01 |

**[Body]**
- 탭에서 **"JSON"** 선택
- 다음을 붙여넣기:
```json
{
  "model": "claude-opus-4-1-20250805",
  "max_tokens": 2048,
  "system": "당신은 금융·경제 뉴스 분석 전문가입니다. 주어진 텍스트에서 투자 관련 이벤트를 JSON 형식으로 추출합니다.",
  "messages": [
    {
      "role": "user",
      "content": "제목: {{ $json.title }}\n출처: {{ $json.source_name }}\n\n본문:\n{{ $json.text }}\n\n위 텍스트를 분석하고 투자 이벤트를 JSON으로 추출해주세요."
    }
  ]
}
```

---

## ✅ Step 4: 노드 연결

### 4-1. 연결 순서
```
1. RSS 피드 트리거
2. 새 게시물 비교하기
3. HTML 콘텐츠 가져오기
4. 블로그 텍스트 추출
5. ✅ Claude AI 분석 (새로 추가)
6. FTTS 워짓 (기존) → Claude 결과로 업데이트
7. FTTS API로 전송
8. 디스코드에 게시
```

### 4-2. Claude 결과를 다음 노드와 연결
1. **"Claude AI 분석" 노드의 오른쪽 끝** → 마우스 드래그
2. **"FTTS 워짓" 노드의 왼쪽 끝**에 연결

---

## 🧪 Step 5: 테스트 실행

### 5-1. 워크플로 실행
1. 우상단 **"Execute workflow"** 또는 **"Test"** 버튼 클릭
2. 또는 수동 실행: RSS 피드에서 새 항목 대기

### 5-2. 결과 확인
1. 각 노드를 클릭해서 **입출력 확인**
2. **"Claude AI 분석" 노드 결과**:
   ```json
   {
     "events": [...],
     "overall_sentiment": 0.75,
     "market_impact": "긍정적|부정적|중립",
     "key_takeaway": "..."
   }
   ```

### 5-3. 오류 발생 시
- **"Claude AI 분석" 노드** 클릭
- 우측 **"Errors"** 탭 확인
- API 키, URL, Model명 다시 확인

---

## 🔗 Step 6: FTTS API와 연결

### 6-1. 현재 상태
- ❌ "FTTS API로 전송" 노드: URL 에러 (필요 수정)

### 6-2. FTTS API 노드 수정
1. **"FTTS API로 전송" 노드** 클릭
2. **Method**: `POST`
3. **URL**:
   ```
   http://localhost:8000/analyze
   ```
4. **Headers**:
   - `Content-Type: application/json`

5. **Body** (JSON):
   ```json
   {
     "text": "{{ $json.text }}",
     "source_name": "{{ $json.source_name || 'RSS' }}",
     "title": "{{ $json.title }}",
     "url": "{{ $json.url }}"
   }
   ```

---

## 🎯 Step 7: Discord 연결 최종 확인

1. **"디스코드에 게시" 노드** 클릭
2. **Webhook URL**: Discord 채널 Webhook URL 확인
3. **Message** 설정:
   ```
   제목: {{ $json.title }}
   이벤트: {{ $json.events.length }}개 감지
   감정: {{ $json.overall_sentiment }}
   ```

---

## 📊 최종 워크플로 구조

```
┌─ RSS 피드 트리거
│
├─ 새 게시물 비교하기
│
├─ HTML 콘텐츠 가져오기
│
├─ 블로그 텍스트 추출
│
├─ ✨ Claude AI 분석 (NEW)
│   └─ 이벤트, 감정, 시장 영향도 추출
│
├─ FTTS 워짓 (데이터 준비)
│
├─ FTTS API로 전송
│   └─ http://localhost:8000/analyze
│
├─ FTTS API로 전송 (결과)
│   └─ 매매 신호 수신
│
└─ 디스코드에 게시
    └─ 분석 결과 + 매매 신호 전송
```

---

## ⚡ 빠른 체크리스트

- [ ] n8n 웹 UI 접속 (http://localhost:5678)
- [ ] "Claude AI 분석" 노드 추가
- [ ] API 키 설정 (sk-ant-api03-...)
- [ ] Base URL: https://api.anthropic.com/v1
- [ ] Model: claude-opus-4-1-20250805
- [ ] System Prompt 입력
- [ ] Messages Content 설정
- [ ] "FTTS API로 전송" 노드 URL 수정 (http://localhost:8000/analyze)
- [ ] 워크플로 실행 테스트
- [ ] Discord 메시지 확인

---

## 🚀 완료!

이제 n8n 888 워크플로가:
1. RSS → 텍스트 추출 → **Claude AI 분석** → FTTS 매매신호 → Discord 발송

모든 단계를 완료하면 자동화 완성! 🎉
