import asyncio
import copy

import pytest

from atp.config import Settings
from atp.engine import ControlError, Coordinator, Decision, Fact
from atp.store import Store


class Transport:
    def __init__(self, coordinator):
        self.c = coordinator
        self.spoken = []
        self.instructions = []
        self.speaker = None
        self.order = []
        self.decision = Decision(reply="I will follow up.")
        self.release = None

    async def start(self):
        pass

    async def dial(self):
        pass

    async def close(self):
        if self.release:
            await self.release.wait()

    def interrupt(self):
        self.order.append("interrupt")

    async def set_speaker(self, identity):
        self.speaker = identity
        self.order.append(("speaker", identity))

    async def flush_transcripts(self, identity=None):
        self.order.append("flush")
        await self.c.transcript("admin", "The missing document was faxed today.", True)

    async def dtmf(self, digits):
        self.order.append(("dtmf", digits))

    async def decide(self, instruction):
        self.instructions.append((instruction, copy.deepcopy(self.c.call["transcript"])))
        return self.decision

    async def speak(self, text, epoch):
        self.spoken.append(text)
        self.c.add_agent_turn(text)


@pytest.fixture
async def c(tmp_path):
    settings = Settings(
        _env_file=None,
        app_demo_password="test",
        database_path=str(tmp_path / "db"),
        turn_end_delay_seconds=0.25,
    )
    store = Store(settings.db_path)
    c = Coordinator(settings, store, Transport)
    await c.start("browser")
    await asyncio.sleep(0.01)
    c.session_participants.update(admin="administrator", doc="doctor")
    await c.participant("admin", True)
    await c.participant("doc", True)
    yield c
    await c.end()
    store.close()


async def command(c, role, action, identity="", request="test-request"):
    return await c.control(role, action, request, c.call["revision"], identity)


async def test_breath_then_continuation_cancels_pending_reply(c):
    await c.transcript("payer", "I reviewed the case.", True)
    await asyncio.sleep(0.05)
    await c.transcript("payer", "There is one more", False)
    await asyncio.sleep(0.3)
    assert not c.transport.instructions
    assert not c.transport.spoken
    await c.transcript("payer", "There is one more document we need.", True)
    await asyncio.sleep(0.3)
    assert len(c.transport.spoken) == 1
    assert len(c.transport.instructions[0][1]) == 2


async def test_resumed_speech_cancels_inflight_model_reply(c):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_decision(instruction):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    c.transport.decide = slow_decision
    await c.transcript("payer", "I found the request.", True)
    await asyncio.wait_for(started.wait(), 1)
    await c.transcript("payer", "Actually", False)
    await asyncio.wait_for(cancelled.wait(), 1)
    assert c.call["agent_status"] == "listening"
    assert not c.transport.spoken


async def test_hesitation_does_not_prompt_an_ai_response(c):
    await c.transcript("payer", "Um...", True)
    await asyncio.sleep(0.3)
    assert not c.transport.spoken
    assert not c.transport.instructions


async def test_unfinished_phrase_gets_extra_time(c):
    c.settings.incomplete_turn_delay_seconds = 0.6
    await c.transcript("payer", "The reason is because...", True)
    await asyncio.sleep(0.3)
    assert not c.transport.instructions
    await c.transcript("payer", "we need the prescribing doctor's notes.", True)
    await asyncio.sleep(0.3)
    assert len(c.transport.spoken) == 1


async def test_wait_interrupts_ai_but_acknowledgment_does_not(c):
    c.call["agent_status"] = "speaking"
    before = c.epoch
    await c.transcript("payer", "Yes, that's right.", False)
    assert c.epoch == before
    await c.transcript("payer", "Wait", False)
    assert c.epoch > before


async def test_full_handoff_keeps_same_room_and_remembers_last_words(c):
    room = c.call["room"]
    await c.transcript("payer", "Who is calling?", True)
    await asyncio.sleep(0.3)
    assert len(c.transport.spoken) == 1
    await command(c, "administrator", "takeover", "admin")
    await c.transcript("payer", "Our file is missing the form.", True)
    await asyncio.sleep(0.3)
    assert len(c.transport.spoken) == 1
    await command(c, "administrator", "handback", "admin", "return-admin")
    await asyncio.sleep(0.3)
    assert c.transport.order.index("flush") < c.transport.order.index(("speaker", None))
    assert "faxed today" in c.transport.instructions[-1][1][-1]["text"]
    await command(c, "doctor", "takeover", "doc", "doctor-turn")
    await c.transcript("doc", "The synthetic LDL result is 190.", True)
    await command(c, "doctor", "handback", "doc", "return-doctor")
    await asyncio.sleep(0.3)
    assert c.call["room"] == room
    assert c.call["control"] == "ai"
    assert len(c.transport.spoken) == 3
    assert any("LDL" in t["text"] for t in c.transport.instructions[-1][1])


async def test_completion_callback_starts_before_teardown_once_with_frozen_call(c):
    received = []

    async def close():
        c.transport.order.append("closed")

    c.transport.close = close

    def notify(call):
        assert "closed" not in c.transport.order
        assert call["status"] == "ended"
        received.append(call)

    c.notify_completion = notify
    await c.end("Conversation completed.")
    await c.end("Conversation completed.")
    assert len(received) == 1
    c.call["case"]["patient"] = "Changed later"
    assert received[0]["case"]["patient"] != "Changed later"


@pytest.mark.parametrize(
    "reason,failed",
    [
        ("Application shutting down.", False),
        ("Demo time limit reached.", False),
        ("Connection failed.", True),
    ],
)
async def test_incomplete_calls_do_not_queue_completion(c, reason, failed):
    received = []
    c.notify_completion = received.append
    await c.end(reason, failed=failed)
    assert received == []


async def test_exclusive_speaker_and_stale_controls(c):
    await command(c, "administrator", "takeover", "admin")
    with pytest.raises(ControlError):
        await command(c, "doctor", "takeover", "doc")
    with pytest.raises(ControlError):
        await command(c, "doctor", "handback", "doc")
    with pytest.raises(ControlError):
        await command(c, "doctor", "pause", "doc")
    with pytest.raises(ControlError):
        await c.control("operator", "pause", "stale-request", 0)
    assert c.call["control"] == "administrator"


async def test_takeover_cancels_pending_reply(c):
    await c.transcript("payer", "Please explain.", True)
    await command(c, "administrator", "takeover", "admin")
    await asyncio.sleep(0.35)
    assert not c.transport.spoken
    assert c.transport.speaker == "admin"


async def test_idempotent_takeover_and_disconnect(c):
    await command(c, "administrator", "takeover", "admin")
    rev = c.call["revision"]
    await c.control("administrator", "takeover", "test-request", 0, "admin")
    assert c.call["revision"] == rev
    await c.participant("admin", False)
    assert c.call["control"] == "paused"
    assert c.call["status"] == "active"
    assert c.call["error"]
    await command(c, "operator", "handback", request="recover-call")
    assert c.call["control"] == "ai"


async def test_escalation_and_evidence_provenance(c):
    c.transport.decision = Decision(
        reply="I will bring in our doctor.", escalation_role="doctor", reason="Clinical review"
    )
    await c.transcript("payer", "A doctor must discuss the evidence.", True)
    await asyncio.sleep(0.35)
    assert c.call["control"] == "handoff_pending"
    assert c.snapshot()["briefing"] if "briefing" in c.snapshot() else True
    assert "briefing" not in c.snapshot()
    payer_turn = c.call["transcript"][0]["id"]
    ai_turn = c.call["transcript"][1]["id"]
    c.apply_facts(
        [
            Fact(field="authorization_status", value="approved", evidence_turn_ids=[ai_turn]),
            Fact(field="requirements", value="Clinical review", evidence_turn_ids=[payer_turn]),
        ],
        c.call["id"],
    )
    assert "authorization_status" not in c.call["facts"]
    assert c.call["facts"]["requirements"]["source"] == "payer"
    await c.transcript("payer", "Is anyone there?", True)
    await asyncio.sleep(0.3)
    assert len(c.transport.spoken) == 1


async def test_start_blocked_until_cleanup_finishes(c):
    c.transport.release = asyncio.Event()
    release = c.transport.release
    ending = asyncio.create_task(c.end())
    await asyncio.sleep(0.01)
    with pytest.raises(ControlError):
        await c.start("browser")
    release.set()
    await ending
    await c.start("browser")
    await asyncio.sleep(0.01)
    assert c.call["status"] == "active"


async def test_payer_disconnect_ends_call(c):
    await c.participant("payer", False)
    assert c.call["status"] == "ended"


async def test_insurer_voicemail_failure_is_visible_and_never_greeted(c):
    class VoicemailTransport(Transport):
        async def dial(self):
            raise ControlError("Insurer's voicemail answered. The insurer call was ended.")

    await c.end()
    c.transport_factory = VoicemailTransport
    await c.start("phone", "pitch")
    await asyncio.sleep(0.05)
    assert c.call["status"] == "failed"
    assert "voicemail" in c.call["error"]
    assert not c.transport.spoken
    assert not c.call["transcript"]


async def test_failed_audio_transfer_never_claims_human_or_ai_control(c):
    async def unavailable(identity):
        raise RuntimeError("Simulated network failure")

    c.transport.set_speaker = unavailable
    with pytest.raises(ControlError):
        await command(c, "administrator", "takeover", "admin")
    assert c.call["control"] == "paused"
    assert "not confirmed" in c.call["error"]
    await c.transcript("payer", "Are you there?", True)
    await asyncio.sleep(0.3)
    assert not c.transport.spoken


async def test_unavailable_human_requests_next_contact(c):
    c.call.update(control="handoff_pending", briefing={"role": "doctor", "reason": "Clinical review"})
    await command(c, "operator", "unavailable")
    await asyncio.sleep(0.3)
    assert c.call["control"] == "ai"
    assert "unavailable" in c.transport.instructions[-1][0]
    assert "scheduled review" in c.transport.instructions[-1][0]


async def test_restart_marks_interrupted_call_failed(tmp_path):
    settings = Settings(_env_file=None, database_path=str(tmp_path / "recover.db"))
    store = Store(settings.db_path)
    store.put("call:old", {"id": "old", "status": "active", "control": "administrator"})
    recovered = Coordinator(settings, store)
    recovered.recover()
    assert recovered.call["status"] == "failed"
    assert recovered.call["control"] == "paused"
    assert "restarted" in recovered.call["error"]
    store.close()


async def test_phone_escalation_calls_doctor_and_notifies_without_operator(c):
    c.call["mode"] = "phone"
    c.call["contacts"]["doctor_phone_number"] = "+12025550123"
    notifications = []

    async def dial_doctor(number, identity):
        assert number == "+12025550123"
        await c.participant(identity, True)

    async def notify(call, attempt):
        notifications.append(attempt["identity"])
        attempt["notification_status"] = "posted"

    c.transport.dial_doctor = dial_doctor
    c.notify_doctor = notify
    c.transport.decision = Decision(
        reply="I will bring in our doctor.", escalation_role="doctor", reason="Need clinical review"
    )
    await c.transcript("payer", "Please get the doctor to review this.", True)
    await asyncio.sleep(0.4)
    assert c.call["control"] == "doctor"
    assert c.call["doctor_call"]["status"] == "connected"
    assert notifications == [c.call["controller_identity"]]
    assert c.call["doctor_call"]["briefing"]["reason"] == "Need clinical review"
    assert "doctor_call" not in c.snapshot()
    assert "contacts" not in c.snapshot()
    identity = c.call["controller_identity"]
    await c.phone_handback("payer")
    assert c.call["control"] == "doctor"
    c.transport.decision = Decision(reply="Thank you, I will continue.")
    await c.phone_handback(identity)
    assert c.call["control"] == "ai"
    assert c.call["doctor_call"]["status"] == "returned"
    assert c.call["status"] == "active"


async def test_doctor_disconnect_after_handback_preserves_insurer(c):
    identity = "doctor-phone-test"
    c.call.update(mode="phone", scenario="pitch")
    c.session_participants[identity] = "doctor"
    await c.participant("payer", True)
    await c.participant(identity, True)
    await command(c, "doctor", "takeover", identity)
    c.call["doctor_call"] = {"identity": identity, "status": "connected"}
    await c.phone_handback(identity)
    await c.participant(identity, False, disconnect_reason="PARTICIPANT_REMOVED")
    await asyncio.sleep(0.35)
    assert c.call["status"] == "active"
    assert c.call["control"] == "ai"
    assert "payer" in c.call["participants"]
    assert c.call["transcript"][-1]["text"] == "Thank you. Can you confirm the final authorization decision?"
    assert any("PARTICIPANT_REMOVED" in e["text"] for e in c.call["events"])


async def test_doctor_can_retry_pound_after_transcription_timeout(c):
    from unittest.mock import AsyncMock

    identity = "doctor-phone-test"
    c.call.update(mode="phone", scenario="pitch")
    c.session_participants[identity] = "doctor"
    await c.participant(identity, True)
    await command(c, "doctor", "takeover", identity)
    c.call["doctor_call"] = {"identity": identity, "status": "connected"}
    c.transport.flush_transcripts = AsyncMock(side_effect=[TimeoutError(), None])
    await c.phone_handback(identity)
    assert c.call["control"] == "paused"
    assert c.call["controller_identity"] == identity
    await c.phone_handback(identity)
    assert c.call["control"] == "ai"
    assert c.call["status"] == "active"
    assert c.transport.flush_transcripts.await_args.args == (identity,)


async def test_no_answer_preserves_insurer_and_records_failure(c):
    c.call["mode"] = "phone"
    c.call["contacts"]["doctor_phone_number"] = "+12025550123"

    async def no_answer(number, identity):
        raise TimeoutError()

    async def remove(identity):
        pass

    c.transport.dial_doctor = no_answer
    c.transport.remove_doctor = remove
    c.call["control"] = "handoff_pending"
    c.request_doctor()
    await asyncio.sleep(0.35)
    assert c.call["status"] == "active"
    assert c.call["control"] == "ai"
    assert c.call["doctor_call"]["status"] == "failed"
    assert "couldn't reach our doctor" in c.transport.spoken[-1]
    assert "callback" in c.transport.spoken[-1]

    # Even if the model repeats its escalation, a failed attempt must not redial.
    identity = c.call["doctor_call"]["identity"]
    c.transport.decision = Decision(reply="Calling again", escalation_role="doctor")
    await c.transcript("payer", "I still need the doctor.", True)
    await asyncio.sleep(0.35)
    assert c.call["control"] == "ai"
    assert c.call["doctor_call"]["identity"] == identity
    assert "unavailable" in c.transport.spoken[-1]


async def test_operator_can_explicitly_retry_after_doctor_failure(c):
    c.call.update(control="ai", doctor_call={"status": "failed", "briefing": {"reason": "Review"}})

    async def dial(number, identity):
        await c.participant(identity, True)

    c.call["contacts"]["doctor_phone_number"] = "+12025550123"
    c.transport.dial_doctor = dial
    c.request_doctor()
    await c.doctor_task
    assert c.call["control"] == "doctor"
    assert c.call["doctor_call"]["status"] == "connected"


async def test_answer_after_operator_resumes_is_not_joined(c):
    answered = asyncio.Event()
    removed = []
    c.call["contacts"]["doctor_phone_number"] = "+12025550123"

    async def dial(number, identity):
        await answered.wait()

    async def remove(identity):
        removed.append(identity)

    c.transport.dial_doctor = dial
    c.transport.remove_doctor = remove
    c.call["control"] = "handoff_pending"
    c.request_doctor()
    await asyncio.sleep(0.01)
    c.call["control"] = "ai"
    answered.set()
    await c.doctor_task
    assert removed == [c.call["doctor_call"]["identity"]]
    assert c.call["doctor_call"]["status"] == "cancelled"


async def test_browser_agent_greets_without_a_prompt(c):
    await c.participant("payer", True)
    await asyncio.sleep(0.35)
    assert c.transport.spoken
    assert "Introduce yourself" in c.transport.instructions[0][0]


async def test_short_partial_does_not_cancel_speech(c):
    c.call["agent_status"] = "speaking"
    before = c.epoch
    await c.transcript("payer", "um", False)
    assert c.epoch == before
    await c.transcript("payer", "Stop", False)
    assert c.epoch > before


async def test_first_turn_after_handback_does_not_immediately_recall_doctor(c):
    await command(c, "doctor", "takeover", "doc")
    c.transport.decision = Decision(
        reply="I need the doctor again.", escalation_role="doctor", reason="Same issue"
    )
    await command(c, "doctor", "handback", "doc", "continue-after-doctor")
    await asyncio.sleep(0.35)
    assert c.call["control"] == "ai"
    assert "next step" in c.transport.spoken[-1]
    assert not c.handoff_resume
    assert c.call["doctor_call"] is None


async def test_pitch_uses_its_own_synthetic_case_without_overwriting_saved_case(c):
    await c.end()
    saved = c.store.get("case")
    saved["patient"] = "Saved case patient"
    c.store.put("case", saved)
    await c.start("browser", "pitch")
    await asyncio.sleep(0.01)
    assert c.call["case"]["patient"] == "Morgan Ellis"
    assert "260 mg/dL" in c.call["case"]["evidence"]
    assert "190 mg/dL" in c.call["case"]["evidence"]
    assert "Only the live doctor can provide that attestation" in c.call["case"]["evidence"]
    assert c.store.get("case")["patient"] == "Saved case patient"
    assert "260 mg/dL" not in c.store.get("case")["evidence"]
    await c.participant("payer", True)
    await asyncio.sleep(0.3)
    assert "I'm ATP" in c.transport.spoken[-1]
    assert not c.transport.instructions  # Greeting does not wait on a model round trip.


async def test_pitch_handback_requests_final_decision_without_another_model_turn(c):
    c.call["scenario"] = "pitch"
    await command(c, "doctor", "takeover", "doc")
    await command(c, "doctor", "handback", "doc", "pitch-handback")
    await asyncio.sleep(0.3)
    assert "final authorization decision" in c.transport.spoken[-1]
    assert c.call["control"] == "ai"
    assert not c.transport.instructions


async def test_public_pitch_status_shows_posted_without_private_update_link(c):
    c.call["docupdates"] = {"notification_status": "posted", "url": "https://private.test/secret"}
    public = c.snapshot()
    assert public["approval_notification_status"] == "posted"
    assert "docupdates" not in public and "private.test" not in str(public)
