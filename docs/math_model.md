# 핵심 수학적 모델

## 가중치 업데이트 (Self-Feedback Loop)

```
결정 시 예측 가중치: W_predicted(x)
실제 시장 영향도:   W_actual(y)
오차:               ε = y - x

가중치 업데이트:
    W_new = W_old + α × ε × confidence_factor

여기서:
    α = 학습률 (기본값 0.1)
    confidence_factor = 정보원 등급 가중치
        S=1.0, A=0.8, B=0.6, C=0.4, D=0.2

정확도 누적:
    accuracy = correct_predictions / total_predictions
    → accuracy ≥ 0.80 이면 모의 → 실전 전환 검토
```

## 복합 이벤트 스코어링

```
event_score = Σ (edge_weight_i × source_grade_i × recency_decay_i)

recency_decay = exp(-0.05 × days_since_event)

최종 신호:
    score > BUY_THRESHOLD  → 매수
    score < SELL_THRESHOLD → 매도
    그 외 → 관망
```
