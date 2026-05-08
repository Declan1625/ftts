"""monitoring/alert_manager.py — 디스코드 신호 알림"""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


class AlertManager:
    """디스코드로 매매 신호 알림 전송."""

    def __init__(self):
        if not DISCORD_WEBHOOK_URL:
            logger.warning("디스코드 웹훅 설정 없음 (DISCORD_WEBHOOK_URL)")
        self.webhook_url = DISCORD_WEBHOOK_URL
        self.enabled = bool(self.webhook_url)

    def send_signal_alert(
        self,
        ticker: str,
        company_name: str,
        signal: str,
        score: float,
        confidence: float,
        source_name: str = "",
    ) -> bool:
        """매매 신호 알림 전송."""
        if not self.enabled:
            logger.debug("디스코드 알림 비활성화")
            return False

        color_map = {"BUY": 0x00FF00, "SELL": 0xFF0000, "HOLD": 0xFFFF00}
        color = color_map.get(signal, 0x808080)

        embed = {
            "title": f"{signal} {ticker}",
            "description": company_name,
            "color": color,
            "fields": [
                {"name": "신뢰도", "value": f"{confidence:.1%}", "inline": True},
                {"name": "점수", "value": f"{score:.3f}", "inline": True},
                {"name": "정보원", "value": source_name or "N/A", "inline": False},
            ],
        }

        payload = {"embeds": [embed]}
        return self._send_webhook(payload)

    def send_batch_alert(
        self,
        signals: list[dict],
        source_name: str = "",
        title: str = "",
    ) -> bool:
        """여러 신호를 한 메시지로 전송."""
        if not self.enabled or not signals:
            return False

        buy_signals = [s for s in signals if s.get("signal") == "BUY"]
        sell_signals = [s for s in signals if s.get("signal") == "SELL"]

        embeds = []

        if buy_signals:
            embed_buy = {
                "title": f"🟢 BUY 신호 ({len(buy_signals)}개)",
                "color": 0x00FF00,
                "fields": [
                    {
                        "name": "종목",
                        "value": ", ".join([f"{s['ticker']}" for s in buy_signals]),
                        "inline": False,
                    }
                ],
            }
            if title:
                embed_buy["fields"].append({"name": "제목", "value": title, "inline": False})
            embeds.append(embed_buy)

        if sell_signals:
            embed_sell = {
                "title": f"🔴 SELL 신호 ({len(sell_signals)}개)",
                "color": 0xFF0000,
                "fields": [
                    {
                        "name": "종목",
                        "value": ", ".join([f"{s['ticker']}" for s in sell_signals]),
                        "inline": False,
                    }
                ],
            }
            if title:
                embed_sell["fields"].append({"name": "제목", "value": title, "inline": False})
            embeds.append(embed_sell)

        if not embeds:
            return False

        payload = {"embeds": embeds}
        return self._send_webhook(payload)

    def _send_webhook(self, payload: dict) -> bool:
        """디스코드 웹훅으로 메시지 전송."""
        if not self.enabled:
            return False

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code in (200, 204):
                logger.info("디스코드 웹훅 전송 성공")
                return True
            else:
                logger.error("디스코드 웹훅 오류 %d: %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as exc:
            logger.error("디스코드 전송 실패: %s", exc)
            return False


# 싱글톤 인스턴스
_alert_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    """디스코드 신호 알림 관리자 인스턴스 반환 (싱글톤)."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
