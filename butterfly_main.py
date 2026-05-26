"""나비효과 AI - Render 진입점"""
import uvicorn
from butterfly.api.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
