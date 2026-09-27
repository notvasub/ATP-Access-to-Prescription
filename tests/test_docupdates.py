import copy
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from atp.config import Settings
from atp.docupdates import ApprovalReview, DocUpdates, ReviewedDetail, build_record
from atp.main import create_app
from atp.store import SEED, Store


def completed_call(call_id="approved-1", mode="phone"):
    return {
        "id": call_id,
        "status": "ended",
        "mode": mode,
        "ended_at": time.time(),
        "case": copy.deepcopy(SEED),
        "sequence": 1,
        "contacts": {"doctor_phone_number": "+12025550121"},
        "transcript": [
            {
                "id": "payer-1",
                "speaker": "payer",
                "text": "The prior authorization is approved. Reference PA-123.",
                "time": time.time(),
            }
        ],
    }


def review(outcome="approved", evidence=None):
    return ApprovalReview(
        outcome=outcome,
        evidence_turn_ids=evidence if evidence is not None else ["payer-1"],
        reference=ReviewedDetail(value="PA-123", evidence_turn_ids=["payer-1"]),
    )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        database_path=str(tmp_path / "updates.db"),
        docupdates_base_url="https://docupdates.vercel.app",
        plivo_auth_id="test",
        plivo_auth_token="test",
        plivo_phone_number="+12025550120",
    )


async def test_approval_persists_before_slack_and_sends_once(settings):
    store = Store(settings.db_path)
    sent = []

    async def reviewer(*args):
        return review()

    async def sender(config, message):
        assert store.get("call:approved-1")["docupdates"]["url"] in str(message)
        sent.append(message)
        return "msg-1"

    service = DocUpdates(
        settings,
        store,
        lambda: "https://demo-test.trycloudflare.com",
        lambda _: None,
        reviewer=reviewer,
        sender=sender,
    )
    call = completed_call()
    service.enqueue(call)
    service.enqueue(copy.deepcopy(call))
    await service.wait()
    saved = store.get("call:approved-1")["docupdates"]
    assert saved["state"] == "ready" and saved["notification_status"] == "posted"
    assert len(sent) == 1
    assert "approved" in str(sent[0]).lower() and "Morgan Ellis" in str(sent[0])
    assert "PA-123" in str(sent[0])
    url = urlsplit(saved["url"])
    assert url.netloc == "docupdates.vercel.app"
    assert parse_qs(url.query)["source"] == ["https://demo-test.trycloudflare.com"]
    token = url.path.split("/")[-1]
    record = service.lookup(token)
    assert record["patient"] == SEED["patient"]
    assert record["authorizationId"] == "PA-123"
    assert record["coveragePeriod"] == "Not specified by payer"
    assert "transcript" not in record and "contacts" not in record
    assert "evidence" not in record and record["source"] == "atp"
    assert not service.lookup(token + "tampered")
    # Restarting the service never silently resends a text already attempted.
    service.enqueue(store.get("call:approved-1"))
    await service.wait()
    assert len(sent) == 1
    store.close()


@pytest.mark.parametrize(
    "outcome,evidence",
    [
        ("pending", ["payer-1"]),
        ("denied", ["payer-1"]),
        ("unknown", []),
        ("approved", []),
        ("approved", ["ai-1"]),
        ("approved", ["missing"]),
        ("approved", ["doctor-1"]),
    ],
)
async def test_never_publish_unconfirmed_approval(settings, outcome, evidence):
    store = Store(settings.db_path)

    async def reviewer(*args):
        return review(outcome, evidence)

    async def sender(*args):
        pytest.fail("A non-approved call must not send an approval Slack message")

    service = DocUpdates(
        settings,
        store,
        lambda: "https://demo-test.trycloudflare.com",
        lambda _: None,
        reviewer=reviewer,
        sender=sender,
    )
    call = completed_call()
    call["transcript"] += [
        {"id": "ai-1", "speaker": "ai", "text": "Approved"},
        {"id": "doctor-1", "speaker": "doctor", "text": "Approved"},
    ]
    service.enqueue(call)
    await service.wait()
    state = store.get("call:approved-1")["docupdates"]
    assert state["state"] == "not_approved" and not state.get("url")
    store.close()


async def test_failed_call_and_browser_rehearsal_do_not_post(settings):
    store = Store(settings.db_path)

    async def reviewer(*args):
        return review()

    async def sender(*args):
        pytest.fail("Rehearsal must not text")

    service = DocUpdates(
        settings,
        store,
        lambda: "https://demo-test.trycloudflare.com",
        lambda _: None,
        reviewer=reviewer,
        sender=sender,
    )
    failed = completed_call("failed")
    failed["status"] = "failed"
    service.enqueue(failed)
    service.enqueue(completed_call(mode="browser"))
    await service.wait()
    assert not store.get("call:failed")
    assert store.get("call:approved-1")["docupdates"]["notification_status"] == "rehearsal"
    store.close()


async def test_slack_failure_preserves_working_record(settings):
    store = Store(settings.db_path)

    async def reviewer(*args):
        return review()

    async def sender(*args):
        raise RuntimeError("Slack rejected the message (HTTP 403). Check the webhook and channel.")

    service = DocUpdates(
        settings,
        store,
        lambda: "https://demo-test.trycloudflare.com",
        lambda _: None,
        reviewer=reviewer,
        sender=sender,
    )
    service.enqueue(completed_call())
    await service.wait()
    status = store.get("call:approved-1")["docupdates"]
    assert status["state"] == "ready" and status["notification_status"] == "failed"
    assert "Slack" in status["error"] and status["url"]
    store.close()


async def test_ambiguous_submission_is_not_reported_as_posted(settings):
    store = Store(settings.db_path)

    async def reviewer(*args):
        return review()

    async def sender(*args):
        raise httpx.ReadTimeout("timeout")

    service = DocUpdates(
        settings,
        store,
        lambda: "https://demo-test.trycloudflare.com",
        lambda _: None,
        reviewer=reviewer,
        sender=sender,
    )
    service.enqueue(completed_call())
    await service.wait()
    assert store.get("call:approved-1")["docupdates"]["notification_status"] == "unconfirmed"
    store.close()


async def test_different_calls_keep_their_own_snapshot(settings):
    store = Store(settings.db_path)

    async def reviewer(*args):
        return review()

    service = DocUpdates(
        settings, store, lambda: "https://demo-test.trycloudflare.com", lambda _: None, reviewer=reviewer
    )
    a, b = completed_call("a", "browser"), completed_call("b", "browser")
    b["case"]["patient"] = "Second Patient"
    service.enqueue(a)
    service.enqueue(b)
    await service.wait()
    tokens = [urlsplit(store.get("call:" + i)["docupdates"]["url"]).path.split("/")[-1] for i in ["a", "b"]]
    assert tokens[0] != tokens[1]
    assert service.lookup(tokens[0])["patient"] == "Morgan Ellis"
    assert service.lookup(tokens[1])["patient"] == "Second Patient"
    store.close()


def test_unknown_and_unsubstantiated_fields_are_not_invented():
    result = review()
    result.coverage = ReviewedDetail(value="12 months", evidence_turn_ids=["missing"])
    record = build_record(completed_call(), result)
    assert record["coveragePeriod"] == "Not specified by payer"
    assert record["quantity"] == "Not specified by payer"
    assert record["generic"] == ""
    assert record["completedAt"] != "2026-09-26T14:42:00-04:00"


async def test_unfinalized_payer_speech_blocks_approval(settings):
    store = Store(settings.db_path)

    async def reviewer(*args):
        pytest.fail("An incomplete transcript must not be treated as a final decision")

    service = DocUpdates(
        settings, store, lambda: "https://demo-test.trycloudflare.com", lambda _: None, reviewer=reviewer
    )
    call = completed_call()
    call["approval_transcript_incomplete"] = True
    service.enqueue(call)
    await service.wait()
    saved = store.get("call:approved-1")["docupdates"]
    assert saved["state"] == "review_failed"
    assert saved["notification_status"] == "not_sent"
    assert not saved.get("url")
    store.close()


async def test_public_endpoint_is_scoped_expiring_and_cors_limited(settings):
    app = create_app(settings)
    service = app.state.docupdates

    async def reviewer(*args):
        return review()

    service.reviewer = reviewer
    service.public_url = lambda: "https://demo-test.trycloudflare.com"
    service.enqueue(completed_call(mode="browser"))
    await service.wait()
    saved = service.store.get("call:approved-1")["docupdates"]
    token = urlsplit(saved["url"]).path.split("/")[-1]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://atp.test"
    ) as client:
        response = await client.get(
            "/api/docupdates/" + token, headers={"Origin": "https://docupdates.vercel.app"}
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "https://docupdates.vercel.app"
        assert response.headers["Cache-Control"] == "no-store"
        assert (await client.get("/api/case")).status_code == 401
        denied = await client.get("/api/docupdates/" + token, headers={"Origin": "https://evil.test"})
        assert "Access-Control-Allow-Origin" not in denied.headers
        assert (await client.get("/api/docupdates/bogus")).status_code == 404
        stored = service.store.get(service.record_key(token))
        stored["expires_at"] = time.time() - 1
        service.store.put(service.record_key(token), stored)
        assert (await client.get("/api/docupdates/" + token)).status_code == 410
    service.store.close()


async def test_review_exception_and_missing_tunnel_never_send(settings):
    store = Store(settings.db_path)

    async def bad_review(*args):
        raise TimeoutError

    async def good_review(*args):
        return review()

    async def sender(*args):
        pytest.fail("No usable update should be texted")

    service = DocUpdates(settings, store, lambda: "", lambda _: None, reviewer=bad_review, sender=sender)
    service.enqueue(completed_call("timeout"))
    await service.wait()
    assert store.get("call:timeout")["docupdates"]["state"] == "review_failed"
    service.reviewer = good_review
    service.enqueue(completed_call("no-tunnel"))
    await service.wait()
    assert store.get("call:no-tunnel")["docupdates"]["state"] == "no_public_url"
    store.close()
