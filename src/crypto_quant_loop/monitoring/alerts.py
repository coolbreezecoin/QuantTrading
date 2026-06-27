from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool = False
    channel: str | None = None


def send_alert(config: AlertConfig, *, title: str, body: str) -> dict[str, str]:
    if not config.enabled:
        return {"status": "alert_disabled", "title": title, "body": body}
    if config.channel is None:
        return {"status": "alert_not_configured", "title": title, "body": body}
    return {"status": "alert_ready_for_connector", "channel": config.channel, "title": title}
