import json

import httpx
import pytest

from atp.config import Settings
from atp.notifications import approval_message, briefing_message, send_slack

WEBHOOK = "https://hooks.slack.com/services/TTEST/BTEST/secret-test"


@pytest.fixture
def slack_client(monkeypatch):
    from atp import notifications

    real_client = httpx.AsyncClient
    requests = []

    def setup(status=200, text="ok", fail=False):
        def handle(request):
            requests.append(request)
            if fail:
                raise httpx.ReadTimeout("Secret URL: " + WEBHOOK, request=request)
            return httpx.Response(status, text=text)

        monkeypatch.setattr(
            notifications.httpx,
            "AsyncClient",
            lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
        )
        return requests

    return setup


async def test_slack_posts_blocks_and_only_claims_posted(slack_client):
    requests = slack_client()
    payload = approval_message("https://docupdates.example/u/test")
    result = await send_slack(Settings(_env_file=None, slack_webhook_url=WEBHOOK), payload)
    assert result == "posted"
    assert len(requests) == 1
    sent = json.loads(requests[0].content)
    assert sent["blocks"][-2]["elements"][0]["url"] == "https://docupdates.example/u/test"
    assert sent["unfurl_links"] is False
    assert "Authorization" not in requests[0].headers


@pytest.mark.parametrize(
    "status,text", [(403, WEBHOOK), (429, "rate_limited"), (200, "invalid_payload"), (302, "redirect")]
)
async def test_slack_rejections_are_not_success_or_secret_leaks(slack_client, status, text):
    requests = slack_client(status, text)
    with pytest.raises(RuntimeError) as error:
        await send_slack(Settings(_env_file=None, slack_webhook_url=WEBHOOK), approval_message(""))
    assert WEBHOOK not in str(error.value)
    assert "secret-test" not in str(error.value)
    assert len(requests) == 1  # No duplicate posts on ambiguous responses.


async def test_slack_timeout_is_sanitized(slack_client):
    requests = slack_client(fail=True)
    with pytest.raises(RuntimeError, match="could not be confirmed") as error:
        await send_slack(Settings(_env_file=None, slack_webhook_url=WEBHOOK), approval_message(""))
    assert WEBHOOK not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://hooks.slack.com/services/A/B/C",
        "https://evil.test/services/A/B/C",
        "https://hooks.slack.com.evil.test/services/A/B/C",
    ],
)
async def test_only_configured_slack_webhooks_are_used(slack_client, url):
    requests = slack_client()
    with pytest.raises(RuntimeError, match="SLACK_WEBHOOK_URL"):
        await send_slack(Settings(_env_file=None, slack_webhook_url=url), approval_message(""))
    assert not requests


def test_briefing_contains_escaped_recap_reason_and_controls():
    payload = briefing_message(
        {"transcript": [{"speaker": "payer", "text": "<!channel> Review <https://evil.test|this> & help."}]},
        {"briefing": {"reason": "Confirm treatment history"}},
        "https://demo.test/join#test",
    )
    text = str(payload)
    assert "<!channel>" not in text and "&lt;!channel&gt;" in text
    assert "Confirm treatment history" in text and "press 1" in text and "Press #" in text
    assert payload["blocks"][-2]["elements"][0]["url"] == "https://demo.test/join#test"
    assert all(len(block.get("text", {}).get("text", "")) <= 3000 for block in payload["blocks"])
