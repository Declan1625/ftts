"""KIS 모의투자 전용 클라이언트"""
from __future__ import annotations
import logging
import requests
import urllib3
from butterfly import config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
BASE = "https://openapivts.koreainvestment.com:9443"


class KISError(Exception):
    pass


class KISPaperClient:
    def __init__(self):
        self.app_key = config.KIS_APP_KEY
        self.app_secret = config.KIS_APP_SECRET
        self.account_no = config.KIS_ACCOUNT
        self.token: str | None = None

    def authenticate(self):
        r = requests.post(f"{BASE}/oauth2/tokenP", json={
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }, timeout=10, verify=False)
        data = r.json()
        self.token = data.get("access_token")
        if not self.token:
            raise KISError(f"토큰 발급 실패: {data}")
        logger.info(f"KIS 인증 성공: token_type={data.get('token_type')} expires={data.get('access_token_token_expired')}")

    def _headers(self, tr_id: str) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "Content-Type": "application/json",
        }

    def get_balance(self) -> dict:
        """모의투자 잔고 조회 - 계좌 유효성 확인용"""
        cano, prdt = self.account_no.split("-")
        r = requests.get(f"{BASE}/uapi/domestic-stock/v1/trading/inquire-balance",
            headers=self._headers("VTTC8434R"),
            params={
                "CANO": cano,
                "ACNT_PRDT_CD": prdt,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "N",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            }, timeout=10, verify=False)
        data = r.json()
        logger.info(f"KIS 잔고 조회: rt_cd={data.get('rt_cd')} msg={data.get('msg1')} msg_cd={data.get('msg_cd')}")
        return data

    def get_price(self, ticker: str) -> float:
        r = requests.get(f"{BASE}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=self._headers("FHKST01010100"),
            params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": ticker},
            timeout=10, verify=False)
        data = r.json()
        if data.get("rt_cd") != "0":
            raise KISError(f"주가 조회 실패 [{ticker}]: {data.get('msg1')}")
        price = float(data["output"].get("stck_prpr", 0))
        logger.info(f"주가 조회: {ticker} = {price:,.0f}원")
        return price

    def buy(self, ticker: str, qty: int, price: int) -> str:
        cano, prdt = self.account_no.split("-")
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt,
            "PDNO": ticker,
            "ORD_DVSN": "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price),
        }
        logger.info(f"KIS 주문 요청: CANO={cano} PRDT={prdt} {ticker} {qty}주 @{price}")
        r = requests.post(f"{BASE}/uapi/domestic-stock/v1/trading/order-cash",
            headers=self._headers("VTTC0802U"),
            json=body, timeout=10, verify=False)
        data = r.json()
        logger.info(f"KIS 주문 응답: {data}")
        if data.get("rt_cd") != "0":
            raise KISError(f"매수 실패 [{ticker}]: {data.get('msg1')}")
        order_no = data.get("output", {}).get("ODNO", "")
        logger.info(f"매수 주문 완료: {ticker} {qty}주 @{price:,}원 주문번호={order_no}")
        return order_no
