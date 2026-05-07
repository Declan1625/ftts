# FTTS FastAPI를 Render에 배포

## 🎯 목표
n8n Cloud → Render의 FTTS API 연동

## 📋 준비물
- GitHub 계정 (FTTS 코드 업로드)
- Render 계정 (무료)
- ANTHROPIC_API_KEY

---

## 🚀 Step 1: GitHub에 코드 업로드

### 1-1. Git 초기화 (처음 한 번만)
```bash
cd ~/Library/Mobile\ Documents/com~apple~CloudDocs/FTTS
git init
git add .
git commit -m "Initial commit: FTTS system"
git remote add origin https://github.com/YOUR_USERNAME/ftts.git
git push -u origin main
```

### 1-2. 계속 업데이트
```bash
git add -A
git commit -m "Update FTTS API"
git push origin main
```

---

## 🌐 Step 2: Render에서 배포

### 2-1. Render 가입
1. https://render.com 접속
2. **"Sign up"** → GitHub로 가입 (권장)

### 2-2. 새 Web Service 생성
1. **Dashboard** → **"New +"** → **"Web Service"**
2. **"Connect a repository"** 클릭
3. GitHub에서 `ftts` 레포 선택

### 2-3. 배포 설정

| 항목 | 값 |
|------|-----|
| Name | `ftts-api` |
| Environment | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn api.server:app --host 0.0.0.0 --port 10000` |
| Plan | Free |

### 2-4. Environment Variables 추가
1. **"Environment"** 탭 클릭
2. **"Add Environment Variable"** 클릭
3. 다음 추가:

```
ANTHROPIC_API_KEY=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

DATABASE_URL=sqlite:///./ftts.db

DB_ECHO=false
```

### 2-5. Deploy 클릭
- **"Create Web Service"** 버튼
- 배포 시작 (2-3분 대기)

---

## ✅ Step 3: 배포 확인

### 3-1. Render Dashboard에서 확인
- 상태: **"Live"** (초록색)
- URL: `https://ftts-api.onrender.com` (예시)

### 3-2. API 테스트
```bash
curl -X POST https://ftts-api.onrender.com/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "text": "SK하이닉스가 미국 칩 수출 제한으로 영향받습니다",
    "source_name": "테스트",
    "title": "테스트",
    "url": "http://test"
  }'
```

---

## 🔗 Step 4: n8n Cloud 연동

### 4-1. Render URL 확인
- Dashboard에서 배포된 URL 복사
- 예: `https://ftts-api.onrender.com`

### 4-2. n8n Cloud 워크플로 수정
1. https://declan1625.app.n8n.cloud/workflow/NxyvEhZJLN2Fg1Xy 접속
2. **"FTTS API로 전송" 노드** 클릭
3. **URL 변경:**
   ```
   https://ftts-api.onrender.com/analyze
   ```
4. **Save & Test**

### 4-3. 테스트 실행
- n8n에서 **"Execute Workflow"** 클릭
- 응답 확인

---

## ⚠️ 주의사항

### Free Plan 제한
- 자동 종료: 15분 이상 요청 없으면 sleep
- 첫 요청 시 10초 정도 지연 가능
- 월 750 hours 무료 (충분함)

### Sleep 방지 (선택사항)
```bash
# Render URL을 자동으로 핑하는 스크립트 (선택)
while true; do
  curl -s https://ftts-api.onrender.com/docs > /dev/null
  sleep 600  # 10분마다
done
```

### 필요시 업그레이드
- Pro Plan: $7/month (자동 종료 없음)

---

## 🔄 배포 후 업데이트

코드 수정 후:
```bash
git add -A
git commit -m "Update message"
git push origin main
```

→ Render가 자동으로 감지해서 재배포 (1-2분)

---

## 📊 최종 아키텍처

```
n8n Cloud (n8n.cloud)
    ↓ HTTP POST /analyze
Render (ftts-api.onrender.com)
    ↓
FastAPI + Claude API
    ↓
Response (event, sentiment, signals)
    ↓ 
Discord
```

---

## 🆘 문제 해결

### "502 Bad Gateway"
- Render logs 확인
- Start Command 다시 확인
- Python 버전 호환성 확인

### "Connection refused"
- API가 `0.0.0.0`로 바인딩되어 있는지 확인
- Port 10000 사용 확인

### timeout
- 첫 배포는 느림 (10초 정도)
- 재시도

---

## ✨ 준비 완료!

1. GitHub에 코드 푸시
2. Render에 배포
3. n8n Cloud에서 URL 변경
4. 테스트!

Let's go! 🚀
