#!/usr/bin/env python3
"""
scripts/setup_n8n_workflow.py — n8n 888 워크플로 자동 생성 스크립트

n8n API를 통해 FTTS 연동 워크플로를 자동으로 생성합니다.
"""

import json
import requests
import time
from typing import Any, Dict

N8N_API = "http://localhost:5678/api/v1"
N8N_WEBHOOK = "http://localhost:5678/webhook"
FTTS_API = "http://localhost:8000/analyze"

def wait_for_n8n(timeout: int = 30) -> bool:
    """n8n이 준비될 때까지 대기"""
    for i in range(timeout):
        try:
            resp = requests.get(f"{N8N_API}/health", timeout=2)
            if resp.status_code == 200:
                print("✅ n8n API 준비 완료")
                return True
        except:
            pass
        time.sleep(1)
    print("❌ n8n API 연결 실패")
    return False

def create_workflow() -> Dict[str, Any]:
    """FTTS 연동 워크플로 JSON 구성"""
    workflow = {
        "name": "FTTS 888 Pipeline",
        "active": True,
        "nodes": [
            {
                "id": "1",
                "name": "Start",
                "type": "n8n-nodes-base.start",
                "typeVersion": 1,
                "position": [50, 50],
            },
            {
                "id": "2",
                "name": "Call FTTS /analyze",
                "type": "n8n-nodes-base.httpRequest",
                "typeVersion": 4,
                "position": [250, 50],
                "parameters": {
                    "url": FTTS_API,
                    "method": "POST",
                    "headerParameters": {
                        "parameters": [
                            {
                                "name": "Content-Type",
                                "value": "application/json"
                            }
                        ]
                    },
                    "bodyParameters": {
                        "parameters": [
                            {
                                "name": "text",
                                "value": "{{ $json.text }}"
                            },
                            {
                                "name": "source_name",
                                "value": "{{ $json.source_name }}"
                            },
                            {
                                "name": "title",
                                "value": "={{ $json.title || '' }}"
                            },
                            {
                                "name": "url",
                                "value": "={{ $json.url || '' }}"
                            }
                        ]
                    },
                    "sendBody": True,
                    "bodyContentType": "json"
                },
                "credentials": {}
            },
            {
                "id": "3",
                "name": "Response",
                "type": "n8n-nodes-base.respondToWebhook",
                "typeVersion": 1,
                "position": [450, 50],
                "parameters": {
                    "responseCode": 200,
                    "body": "={{ $json }}"
                }
            }
        ],
        "connections": {
            "Start": {
                "main": [
                    [
                        {
                            "node": "Call FTTS /analyze",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            },
            "Call FTTS /analyze": {
                "main": [
                    [
                        {
                            "node": "Response",
                            "type": "main",
                            "index": 0
                        }
                    ]
                ]
            }
        },
        "settings": {}
    }
    return workflow

def export_workflow_json(workflow: Dict[str, Any], filepath: str):
    """워크플로 JSON을 파일로 내보내기"""
    with open(filepath, 'w') as f:
        json.dump(workflow, f, indent=2, ensure_ascii=False)
    print(f"✅ 워크플로 JSON 저장: {filepath}")

def print_import_instructions(json_file: str):
    """import 방법 출력"""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           n8n 888 워크플로 import 방법                          ║
╚══════════════════════════════════════════════════════════════════╝

1️⃣  n8n 웹 UI 접속
    URL: http://localhost:5678

2️⃣  Workflow 메뉴 → "Import from file"

3️⃣  생성된 JSON 파일 선택
    파일: """ + json_file + """

4️⃣  Import 완료 후 "Execute" 또는 "Save & Activate"

5️⃣  테스트 요청 (curl):
    curl -X POST http://localhost:5678/webhook/WORKFLOW_ID \\
      -H "Content-Type: application/json" \\
      -d '{
        "text": "테스트 이벤트 텍스트",
        "source_name": "메르블로그",
        "title": "테스트 제목",
        "url": "http://example.com"
      }'

또는 Python으로 테스트:
    python -m scripts.test_n8n_workflow
    """)

if __name__ == "__main__":
    print("🚀 n8n 888 워크플로 생성 시작...")

    # n8n 준비 확인
    if not wait_for_n8n():
        exit(1)

    # 워크플로 JSON 생성
    workflow = create_workflow()

    # JSON 저장
    json_file = "/Users/kangbook/Library/Mobile Documents/com~apple~CloudDocs/FTTS/config/n8n_workflow.json"
    export_workflow_json(workflow, json_file)

    # import 방법 출력
    print_import_instructions(json_file)

    print("\n✅ 준비 완료! 위 방법을 따라 n8n에 워크플로를 import하세요.")
