"""Slack notifications for doctor handoffs and confirmed approval updates."""

import re

import httpx


class NotificationUnconfirmed(RuntimeError):
    """The request may have reached Slack; do not retry or claim delivery."""


def webhook_configured(settings):
    return bool(
        re.fullmatch(
            r"https://hooks\.slack\.com/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+",
            settings.slack_webhook_url,
        )
    )


def escaped(value, limit=2000):
    # Prevent transcript text from becoming Slack mentions or injected links.
    return str(value)[:limit].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def section(heading, text):
    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{heading}*\n{escaped(text, 400)}",
            "verbatim": True,
        },
    }


def message(title, sections, link="", label="Open ATP"):
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": title}}]
    blocks += [section(heading, text) for heading, text in sections]
    if link:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": label},
                        "url": link,
                    }
                ],
            }
        )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "ATP · Access to Prescription · Synthetic hackathon demo",
                }
            ],
        }
    )
    return {"text": title, "blocks": blocks, "unfurl_links": False, "unfurl_media": False}


def briefing_message(call, attempt, link):
    recent = [t["text"] for t in call["transcript"] if t["speaker"] == "payer"][-2:]
    reason = (attempt.get("briefing") or {}).get("reason", "Your input is needed.")
    return message(
        "Doctor needed on the insurer call",
        [
            ("What we discussed", " ".join(recent) or "The insurer requested the doctor."),
            ("What we need from you", reason),
            ("Join the call", "Answer ATP’s phone call and press 1 within 10 seconds to join the insurer."),
            (
                "Hand back to AI",
                "Press # on your phone keypad, or open the controls below and tap Return to AI.",
            ),
        ],
        link,
        "Briefing & call controls",
    )


def approval_message(link, record=None):
    details = []
    if record:
        details = [
            ("Patient / medication", record["patient"] + " · " + record["medication"]),
            ("Authorization reference", record["authorizationId"]),
            ("Coverage", record["coveragePeriod"]),
            ("Next step", record["nextStep"]),
        ]
    return message(
        "Your DocUpdate has been updated",
        [
            (
                "Authorization status",
                "Your request has been approved. Check the latest details and next steps in DocUpdate.",
            ),
            ("Reminder", "Approval does not confirm dispensing or copay."),
        ]
        + details,
        link,
        "View in DocUpdate",
    )


async def send_slack(settings, payload):
    if not webhook_configured(settings):
        raise RuntimeError("Configure SLACK_WEBHOOK_URL for the ATP Slack channel.")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(settings.slack_webhook_url, json=payload)
    except httpx.HTTPError:
        # Never expose the secret URL in request exceptions, logs, or UI errors.
        raise NotificationUnconfirmed(
            "Slack submission could not be confirmed. No automatic retry was attempted."
        ) from None
    if response.status_code != 200 or response.text.strip() != "ok":
        if response.status_code == 429:
            raise RuntimeError("Slack rate limited this message. No automatic retry was attempted.")
        raise RuntimeError(
            f"Slack rejected the message (HTTP {response.status_code}). Check the webhook and channel."
        )
    return "posted"  # Slack acknowledged the post; this does not mean the doctor read it.
