"""monitoring/dashboard.py — Streamlit 실시간 대시보드"""

import logging
from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy import desc, func

from database.db_manager import get_session
from database.models import Event, Source, StockPrice, Company, Decision, Outcome

logger = logging.getLogger(__name__)

st.set_page_config(page_title="FTTS 대시보드", layout="wide", initial_sidebar_state="expanded")
st.title("📈 자가 진단형 주식 자동매매 시스템 (FTTS)")

# ── 사이드바: 날짜 필터 ─────────────────────────────────
st.sidebar.header("⚙️ 설정")
days_back = st.sidebar.slider("조회 기간 (일)", 1, 90, 7)
end_date = datetime.now(timezone.utc).date()
start_date = end_date - timedelta(days=days_back)

# ── 탭 구조 ─────────────────────────────────────────────
tab_events, tab_sources, tab_trades, tab_graph = st.tabs([
    "📰 이벤트",
    "🔗 정보원",
    "💹 매매",
    "🕸️ 인과관계",
])

# ── TAB 1: 이벤트 ──────────────────────────────────────
with tab_events:
    st.subheader("최근 이벤트")

    with get_session() as session:
        events = (
            session.query(Event)
            .filter(Event.occurred_at >= start_date)
            .order_by(desc(Event.occurred_at))
            .limit(50)
            .all()
        )

        if events:
            event_data = []
            for e in events:
                source = session.query(Source).filter_by(id=e.source_id).first()
                event_data.append({
                    "발생일": e.occurred_at.strftime("%Y-%m-%d %H:%M"),
                    "제목": e.title,
                    "유형": e.event_type or "-",
                    "감성": f"{e.sentiment:.2f}" if e.sentiment else "-",
                    "정보원": source.name if source else "-",
                })

            st.dataframe(event_data, use_container_width=True)
        else:
            st.info("조회 기간 내 이벤트 없음")

    # 이벤트 통계
    col1, col2, col3 = st.columns(3)
    with get_session() as session:
        total_events = session.query(func.count(Event.id)).filter(
            Event.occurred_at >= start_date
        ).scalar() or 0

        with col1:
            st.metric("총 이벤트", total_events)

        avg_sentiment = session.query(func.avg(Event.sentiment)).filter(
            Event.occurred_at >= start_date
        ).scalar()
        with col2:
            st.metric("평균 감성", f"{avg_sentiment:.2f}" if avg_sentiment else "-")

        source_count = session.query(func.count(Source.id.distinct())).scalar() or 0
        with col3:
            st.metric("활성 정보원", source_count)

# ── TAB 2: 정보원 ──────────────────────────────────────
with tab_sources:
    st.subheader("정보원 신뢰도")

    with get_session() as session:
        sources = session.query(Source).filter_by(is_active=True).order_by(desc(Source.grade)).all()

        if sources:
            source_data = []
            for s in sources:
                accuracy = (s.correct_predictions / s.total_predictions * 100) if s.total_predictions > 0 else 0
                source_data.append({
                    "이름": s.name,
                    "등급": s.grade,
                    "가중치": f"{s.grade_weight:.2f}",
                    "예측": s.total_predictions,
                    "정확도": f"{accuracy:.1f}%",
                })

            st.dataframe(source_data, use_container_width=True)

            # 등급별 분포
            st.write("#### 등급별 정보원")
            grade_counts = {}
            for s in sources:
                grade_counts[s.grade] = grade_counts.get(s.grade, 0) + 1

            st.bar_chart(grade_counts)
        else:
            st.info("정보원 없음")

# ── TAB 3: 매매 ────────────────────────────────────────
with tab_trades:
    st.subheader("매매 성과")

    with get_session() as session:
        decisions = (
            session.query(Decision)
            .filter(Decision.decided_at >= start_date)
            .order_by(desc(Decision.decided_at))
            .limit(30)
            .all()
        )

        if decisions:
            trade_data = []
            for d in decisions:
                company = session.query(Company).filter_by(id=d.company_id).first()
                outcome = session.query(Outcome).filter_by(decision_id=d.id).first()

                trade_data.append({
                    "종목": company.name if company else "-",
                    "신호": d.signal,
                    "점수": f"{d.event_score:.2f}",
                    "신뢰도": f"{d.confidence:.2f}",
                    "결과": outcome.actual_direction if outcome else "-",
                })

            st.dataframe(trade_data, use_container_width=True)

            # 신호별 통계
            col1, col2, col3 = st.columns(3)
            buy_count = sum(1 for d in decisions if d.signal == "BUY")
            sell_count = sum(1 for d in decisions if d.signal == "SELL")
            hold_count = sum(1 for d in decisions if d.signal == "HOLD")

            with col1:
                st.metric("BUY", buy_count)
            with col2:
                st.metric("SELL", sell_count)
            with col3:
                st.metric("HOLD", hold_count)
        else:
            st.info("조회 기간 내 매매 신호 없음")

# ── TAB 4: 인과관계 그래프 ─────────────────────────────
with tab_graph:
    st.subheader("인과관계 네트워크")
    st.info(
        "이벤트 → 산업 → 기업으로 이어지는 인과관계 그래프입니다.\n"
        "가중치: 영향도 (0~1), 신뢰도: 신뢰 수준"
    )

    with get_session() as session:
        from database.models import CausalEdge

        edges = session.query(CausalEdge).limit(100).all()
        if edges:
            edge_data = []
            for e in edges:
                edge_data.append({
                    "출발": f"{e.from_type}({e.from_id})",
                    "도착": f"{e.to_type}({e.to_id})",
                    "가중치": f"{e.weight:.2f}",
                    "신뢰도": f"{e.confidence:.2f}",
                    "횟수": e.observation_count,
                })

            st.dataframe(edge_data, use_container_width=True)
            st.success(f"총 {len(edges)}개의 인과관계 엣지")
        else:
            st.warning("인과관계 그래프 없음")

# ── 푸터 ───────────────────────────────────────────────
st.divider()
st.caption(f"마지막 업데이트: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
