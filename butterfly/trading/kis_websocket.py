"""KIS WebSocket 실시간 체결 통보
체결 발생 시 Discord 알림 전송
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import httpx
from butterfly import config

logger = logging.getLogger(__name__)

WS_URL = "wss://openapivts.koreainvestment.com:29443/websocket/tryitout/H0STCNI0"


async def _get_approval_key() -> str | None:
    """WebSocket 접속용 approval_key 발급"""
    try:
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                "https://openapivts.koreainvestment.com:9443/oauth2/Approval",
                json={
                    "grant_type": "client_credentials",
                    "appkey": config.KIS_APP_KEY,
                    "secretkey": config.KIS_APP_SECRET,
                },
                timeout=10,
            )
            key = r.json().get("approval_key", "")
            if key:
                logger.info("KIS WebSocket approval_key 발급 완료")
            return key
    except Exception as e:
        logger.warning("approval_key 발급 실패: %s", e)
        return None


async def _send_discord(msg: str):
    if not config.DISCORD_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(config.DISCORD_WEBHOOK, json={"content": msg}, timeout=5)
    except Exception:
        pass


def _parse_execution(data: str) -> dict | None:
    """체결 통보 데이터 파싱 (| 구분자)"""
    try:
        parts = data.split("|")
        if len(parts) < 4:
            return None
        body = parts[3].split("^")
        if len(body) < 15:
            return None
        return {
            "ticker":    body[8],
            "direction": "매수" if body[13] == "02" else "매도",
            "qty":       body[14],
            "price":     body[11],
        }
    except Exception:
        return None


async def listen(stop_event: asyncio.Event | None = None):
    """체결 통보 WebSocket 수신 루프"""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets 패키지 없음 — pip install websockets")
        return

    approval_key = await _get_approval_key()
    if not approval_key:
        logger.warning("approval_key 없음 — WebSocket 시작 불가")
        return

    cano = config.KIS_ACCOUNT.split("-")[0] if config.KIS_ACCOUNT else ""
    subscribe_msg = json.dumps({
        "header": {
            "approval_key": approval_key,
            "custtype": "P",
            "tr_type": "1",
            "content-type": "utf-8",
        },
        "body": {
            "input": {"tr_id": "H0STCNI0", "tr_key": cano},
        },
    })

    reconnect_delay = 5
    while True:
        try:
            logger.info("KIS WebSocket 연결 시도...")
            async with websockets.connect(WS_URL, ssl=False) as ws:
                await ws.send(subscribe_msg)
                logger.info("✅ KIS WebSocket 체결 통보 구독 완료")
                reconnect_delay = 5

                while True:
                    if stop_event and stop_event.is_set():
                        return
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        await ws.ping()
                        continue

                    if msg.startswith("0|") or msg.startswith("1|"):
                        exec_info = _parse_execution(msg)
                        if exec_info:
                            alert = (
                                f"🔔 체결 통보\n"
                                f"종목: {exec_info['ticker']}\n"
                                f"구분: {exec_info['direction']}\n"
                                f"수량: {exec_info['qty']}주\n"
                                f"체결가: {exec_info['price']}원"
                            )
                            logger.info(alert)
                            await _send_discord(alert)
                    elif '"tr_id":"PINGPONG"' in msg:
                        await ws.send(msg)  # PINGPONG 응답

        except Exception as e:
            logger.warning("KIS WebSocket 연결 끊김: %s — %ds 후 재연결", e, reconnect_delay)
            if stop_event and stop_event.is_set():
                return
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 60)
