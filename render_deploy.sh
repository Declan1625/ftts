#!/bin/bash
# Render 배포용 스크립트

echo "🚀 FTTS FastAPI를 Render에 배포합니다..."

# 1. GitHub에 푸시
git add -A
git commit -m "Deploy FastAPI to Render"
git push origin main

echo "✅ GitHub에 푸시 완료"
echo ""
echo "📍 다음 단계:"
echo "1. https://render.com 접속"
echo "2. 'New +' → 'Web Service'"
echo "3. GitHub repo 연결"
echo "4. 다음 설정:"
echo "   - Name: ftts-api"
echo "   - Environment: Python 3"
echo "   - Build Command: pip install -r requirements.txt"
echo "   - Start Command: uvicorn api.paper_trading_api:app --host 0.0.0.0 --port 10000"
echo "5. Deploy 클릭"
echo ""
echo "⚠️  주의: Environment Variables 설정:"
echo "   - DATABASE_URL (PostgreSQL)"
echo "   - KIS_APP_KEY_KR, KIS_APP_SECRET_KR, KIS_ACCOUNT_NO_KR"
echo "   - KIS_APP_KEY_US, KIS_APP_SECRET_US, KIS_ACCOUNT_NO_US"
echo "   - GOOGLE_API_KEY, ANTHROPIC_API_KEY, DISCORD_WEBHOOK_URL"
