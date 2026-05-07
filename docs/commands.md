# 자주 쓰는 명령어

```bash
# 환경 설치
pip install -r requirements.txt

# DB 초기화
python -m database.db_manager --init

# 모의 투자 실행
python -m trading.paper_trader --run

# 정확도 리포트
python -m monitoring.accuracy_tracker --report

# 테스트
pytest tests/test_causal_graph.py -v

# 대시보드
streamlit run monitoring/dashboard.py
```
