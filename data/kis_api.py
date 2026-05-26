"""한국투자증권 (KIS) API 클라이언트.

기능:
1. 토큰 발급 (OAuth)
2. 실시간 주가 조회 (주식현재가)
3. 주문 실행 (매수/매도) — 실전 모드용 (아직 미활성)
4. 계좌 정보 조회
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


class KISAuthError(Exception):
    """KIS 인증 오류."""
    pass


class KISAPIError(Exception):
    """KIS API 오류."""
    pass


class KISClient:
    """한국투자증권 API 클라이언트."""

    BASE_URL = "https://openapi.koreainvestment.com:9443"
    MOCK_BASE_URL = "https://openapivts.koreainvestment.com:9443"  # 모의투자용

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        account_no: str,
        *,
        mock: bool = True,
    ) -> None:
        """
        Args:
            app_key: KIS 앱 키
            app_secret: KIS 앱 시크릿
            account_no: 계좌 번호 (형식: "12345678-01")
            mock: True이면 모의투자 서버 사용, False이면 실전 서버 사용
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.account_no = account_no
        self.mock = mock
        self.base_url = self.MOCK_BASE_URL if mock else self.BASE_URL
        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None

    # ── 인증 ──────────────────────────────────────────────────────
    def authenticate(self) -> bool:
        """토큰 발급. True이면 성공."""
        try:
            response = requests.post(
                f"{self.base_url}/oauth2/tokenP",
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "client_credentials",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret,
                },
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            self.access_token = data.get("access_token")
            # 만료 시간: 발급 후 24시간 (하드코딩)
            self.token_expires_at = datetime.now(timezone.utc)
            if not self.access_token:
                raise KISAuthError("토큰이 응답에 없습니다")
            logger.info("KIS 토큰 발급 성공 (모의투자: %s)", self.mock)
            return True
        except requests.RequestException as e:
            logger.error("KIS 토큰 발급 실패: %s", e)
            raise KISAuthError(f"KIS 인증 실패: {e}") from e

    def is_token_valid(self) -> bool:
        """토큰이 유효한지 확인."""
        return (
            self.access_token is not None
            and self.token_expires_at is not None
            and datetime.now(timezone.utc) < self.token_expires_at
        )

    def refresh_token_if_needed(self) -> None:
        """필요하면 토큰 갱신."""
        if not self.is_token_valid():
            self.authenticate()

    # ── 실시간 주가 조회 ──────────────────────────────────────────
    def get_price(self, ticker: str) -> dict[str, Any]:
        """
        종목의 현재 가격을 조회.

        Args:
            ticker: 종목 코드 (예: "005930" for 삼성전자)

        Returns:
            {
                "ticker": "005930",
                "price": 75000.0,
                "change": 1000.0,
                "change_rate": 0.0137,
                "volume": 8500000,
                "high": 76500.0,
                "low": 74200.0,
                "timestamp": datetime,
            }

        Raises:
            KISAPIError: API 호출 실패
        """
        self.refresh_token_if_needed()
        try:
            headers = self._build_headers()
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker}
            response = requests.get(
                f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
                headers=headers,
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("rt_cd") != "0":
                raise KISAPIError(f"조회 실패: {data.get('msg1')}")
            output = data.get("output", {})
            return {
                "ticker": ticker,
                "price": float(output.get("stck_prpr", 0)),
                "change": float(output.get("prdy_vrss", 0)),
                "change_rate": float(output.get("prdy_ctrt", 0)) / 100,  # % → 비율
                "volume": int(output.get("acml_vol", 0)),
                "high": float(output.get("stck_hgpr", 0)),
                "low": float(output.get("stck_lwpr", 0)),
                "timestamp": datetime.now(timezone.utc),
            }
        except requests.RequestException as e:
            logger.error("KIS 주가 조회 실패 (ticker=%s): %s", ticker, e)
            raise KISAPIError(f"주가 조회 실패: {e}") from e

    def get_prices_batch(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        """여러 종목 가격을 한 번에 조회. 각 ticker별로 순차 호출."""
        result = {}
        for ticker in tickers:
            try:
                result[ticker] = self.get_price(ticker)
            except KISAPIError as e:
                logger.warning("배치 조회 중 %s 실패: %s", ticker, e)
                result[ticker] = None
        return result

    # ── 계좌 정보 ─────────────────────────────────────────────────
    def get_balance(self) -> dict[str, Any]:
        """
        계좌의 현금 잔고 조회.

        Returns:
            {
                "account_no": "12345678-01",
                "cash": 5000000.0,
                "total_assets": 15000000.0,
                "positions_value": 10000000.0,
            }
        """
        self.refresh_token_if_needed()
        try:
            headers = self._build_headers()
            path = f"/uapi/domestic-stock/v1/trading/inquire-balance"
            body = self._build_order_body({})
            response = requests.get(
                f"{self.base_url}{path}",
                headers=headers,
                json=body,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("rt_cd") != "0":
                raise KISAPIError(f"잔고 조회 실패: {data.get('msg1')}")
            output = data.get("output", {})
            return {
                "account_no": self.account_no,
                "cash": float(output.get("scts_ord_unexc_amt", 0)),
                "total_assets": float(output.get("tot_evlu_amt", 0)),
                "positions_value": float(output.get("tot_evlu_amt", 0))
                - float(output.get("scts_ord_unexc_amt", 0)),
            }
        except requests.RequestException as e:
            logger.error("KIS 계좌 조회 실패: %s", e)
            raise KISAPIError(f"계좌 조회 실패: {e}") from e

    # ── 주문 실행 (아직 미활성) ────────────────────────────────────
    def place_buy_order(
        self,
        ticker: str,
        quantity: int,
        price: Optional[float] = None,
        order_type: str = "00",  # 00=시장가, 01=지정가
    ) -> dict[str, Any]:
        """
        매수 주문 실행 (모의투자 전용).

        Args:
            ticker: 종목 코드
            quantity: 매수 수량
            price: 지정가 (order_type이 "01"일 때 필수)
            order_type: "00"=시장가, "01"=지정가

        Returns:
            {"order_number": "123456", "status": "주문접수"}

        Raises:
            KISAPIError: 주문 실패
        """
        if not self.mock:
            raise KISAPIError("실전 주문은 아직 지원하지 않습니다")
        self.refresh_token_if_needed()
        try:
            headers = self._build_headers(method="POST")
            path = "/uapi/domestic-stock/v1/trading/order-cash"
            body = {
                "CANO": self.account_no.split("-")[0],
                "ACNT_PRDT_CD": self.account_no.split("-")[1],
                "PDNO": ticker,
                "ORD_QTY": quantity,
                "ORD_UNPR": int(price or 0),
                "ORD_DVSN": order_type,
                "ORD_SVR_DVSN_CD": "0",
            }
            response = requests.post(
                f"{self.base_url}{path}",
                headers=headers,
                json=body,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            if data.get("rt_cd") != "0":
                raise KISAPIError(f"주문 실패: {data.get('msg1')}")
            output = data.get("output", {})
            logger.info(
                "매수 주문 성공 (ticker=%s, qty=%d, order_no=%s)",
                ticker,
                quantity,
                output.get("ORD_NO"),
            )
            return {
                "order_number": output.get("ORD_NO"),
                "status": "주문접수",
            }
        except requests.RequestException as e:
            logger.error("KIS 주문 실패: %s", e)
            raise KISAPIError(f"주문 실패: {e}") from e

    # ── 내부 헬퍼 ─────────────────────────────────────────────────
    def _build_headers(self, method: str = "GET") -> dict[str, str]:
        """API 요청용 헤더 구성."""
        if not self.access_token:
            raise KISAuthError("토큰이 없습니다. authenticate()를 먼저 호출하세요")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "User-Agent": "FTTS/1.0",
        }

    def _build_order_body(self, params: dict) -> dict:
        """주문 요청 본문 구성."""
        cano, acnt_prdt_cd = self.account_no.split("-")
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "INQR_DVSN_CD": "02",
            "UNPR_DVSN_CD": "01",
            "PRICE_CLS_CODE": "",
            "QTY_CLS_CODE": "",
            "CTAC_TLNO": "",
            "CTAC_TLNO2": "",
            "SOLF_CD": "",
            "ALGO_NO": "",
            "CORP_CD": "",
        }
        body.update(params)
        return body


def create_kis_client_from_env(*, mock: bool = True) -> KISClient:
    """환경 변수에서 KIS 클라이언트 생성."""
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    account_no = os.getenv("KIS_ACCOUNT_NO")

    if not all([app_key, app_secret, account_no]):
        raise ValueError(
            "KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO 환경 변수가 필요합니다"
        )

    client = KISClient(app_key, app_secret, account_no, mock=mock)
    client.authenticate()
    return client
