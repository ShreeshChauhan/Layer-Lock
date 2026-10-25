
import os
import logging
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


async def send_discord_alert(
    failure_type: str,
    risk_score: float,
    printer_status: str = "Paused",
    is_test: bool = False,
    action_message: str = 'Pause command accepted'
) -> bool:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    if not webhook_url:
        logger.error("DISCORD_WEBHOOK_URL is missing")
        return False

    title = (
        "PRINT GUARDIAN - TEST NOTIFICATION"
        if is_test
        else "PRINT GUARDIAN - FAILURE DETECTED"
    )

    action = (
        "Test only - no printer action"
        if is_test
        else action_message
    )

    payload = {
        "username": "Print Guardian",
        "embeds": [
            {
                "title": title,
                "description": (
                    "Testing Discord integration."
                    if is_test
                    else "A printer failure has been detected."
                ),
                "color": 3447003 if is_test else 15158332,
                "fields": [
                    {
                        "name": "Failure Type",
                        "value": str(failure_type),
                        "inline": True
                    },
                    {
                        "name": "Risk Score",
                        "value": f"{risk_score:.1f}%",
                        "inline": True
                    },
                    {
                        "name": "Printer Status",
                        "value": printer_status,
                        "inline": False
                    },
                    {
                        "name": "Action",
                        "value": action,
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "Print Guardian Monitoring System"
                },
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat()
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                webhook_url,
                params={"wait": "true"},
                json=payload
            )

            response.raise_for_status()
            message = response.json()

        logger.info(
            "Discord notification sent: message=%s channel=%s",
            message.get("id"),
            message.get("channel_id")
        )
        return True

    except httpx.HTTPStatusError as error:
        logger.error(
            "Discord HTTP error %s: %s",
            error.response.status_code,
            error.response.text[:300]
        )
        return False

    except (httpx.RequestError, ValueError) as error:
        logger.error("Discord notification error: %s", error)
        return False
