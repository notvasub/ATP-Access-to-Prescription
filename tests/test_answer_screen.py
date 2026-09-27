import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from atp import answer_screen
from atp.answer_screen import AnswerScreen
from atp.engine import ControlError


@pytest.fixture(params=["doctor", "insurer"])
async def screen(monkeypatch, request):
    events = {}
    room = SimpleNamespace(
        on=lambda name: lambda fn: events.setdefault(name, fn),
        connect=AsyncMock(),
        disconnect=AsyncMock(),
        local_participant=SimpleNamespace(publish_track=AsyncMock()),
    )
    source = SimpleNamespace(clear_queue=Mock(), aclose=AsyncMock())
    monkeypatch.setattr(answer_screen.rtc, "Room", lambda: room)
    monkeypatch.setattr(answer_screen.rtc, "AudioSource", lambda *a, **kw: source)
    monkeypatch.setattr(answer_screen.rtc.LocalAudioTrack, "create_audio_track", Mock())
    monkeypatch.setattr(answer_screen, "discover_trunk", AsyncMock(return_value="ST_test"))
    monkeypatch.setattr(answer_screen, "lk_token", Mock(return_value="private-test-token"))
    t = SimpleNamespace(
        s=SimpleNamespace(
            livekit_url="wss://test", plivo_phone_number="+12025550100", demo_max_call_seconds=600
        ),
        c=SimpleNamespace(
            call={
                "room": "insurer-room",
                "status": "dialing",
                "control": "handoff_pending",
                "doctor_call": {"identity": "doctor-phone-test", "status": "calling"},
            },
            emit=Mock(),
        ),
        closed=False,
        screen_rooms=set(),
        lk=SimpleNamespace(
            room=SimpleNamespace(
                create_room=AsyncMock(), delete_room=AsyncMock(), move_participant=AsyncMock()
            ),
            sip=SimpleNamespace(create_sip_participant=AsyncMock()),
        ),
    )
    identity = "doctor-phone-test" if request.param == "doctor" else "payer"
    result = AnswerScreen(t, identity, role=request.param)
    result.say = AsyncMock()
    result.events = events
    return result


async def test_confirmed_human_moves_only_after_press_one(screen):
    async def answer(*args, **kwargs):
        assert not screen.t.lk.room.move_participant.called
        screen.events["sip_dtmf_received"](
            SimpleNamespace(participant=SimpleNamespace(identity=screen.identity), digit="1")
        )

    screen.t.lk.sip.create_sip_participant.side_effect = answer
    await screen.run("+12025550101")
    request = screen.t.lk.sip.create_sip_participant.call_args.args[0]
    assert request.room_name != "insurer-room"
    assert request.sip_call_to == "+12025550101"
    assert request.ringing_timeout.seconds == 30
    assert request.wait_until_answered and not request.play_dialtone
    move = screen.t.lk.room.move_participant.call_args.args[0]
    assert move.room == request.room_name
    assert move.destination_room == "insurer-room"
    assert move.identity == screen.identity
    assert screen.t.lk.room.delete_room.call_args.args[0].room == request.room_name


@pytest.mark.parametrize("outcome", ["voicemail", "unconfirmed", "disconnected"])
async def test_unconfirmed_answers_never_reach_insurer(screen, outcome):
    screen.finish(outcome)
    with pytest.raises(ControlError):
        await screen.run("+12025550101")
    screen.t.lk.room.move_participant.assert_not_called()
    screen.t.lk.room.delete_room.assert_awaited_once()
    if outcome != "disconnected":
        assert "Goodbye" in screen.say.call_args.args[0]
    screen.room.disconnect.assert_awaited_once()


async def test_unconfirmed_answer_times_out_even_without_voicemail_detection(screen, monkeypatch):
    monkeypatch.setattr(answer_screen, "CONFIRM_SECONDS", 0.01)
    with pytest.raises(ControlError, match="did not press 1"):
        await screen.run("+12025550101")
    screen.t.lk.room.move_participant.assert_not_called()
    screen.t.lk.room.delete_room.assert_awaited_once()


async def test_no_answer_cleans_up_without_moving_or_leaving_message(screen):
    screen.t.lk.sip.create_sip_participant.side_effect = TimeoutError
    with pytest.raises(ControlError, match="30 seconds"):
        await screen.run("+12025550101")
    screen.say.assert_not_called()
    screen.t.lk.room.move_participant.assert_not_called()
    screen.t.lk.room.delete_room.assert_awaited_once()


async def test_cancel_during_ringing_cleans_up_screening_room(screen):
    ringing = asyncio.Event()

    async def dial(*args, **kwargs):
        ringing.set()
        await asyncio.Event().wait()

    screen.t.lk.sip.create_sip_participant.side_effect = dial
    task = asyncio.create_task(screen.run("+12025550101"))
    await ringing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    screen.t.lk.room.move_participant.assert_not_called()
    screen.t.lk.room.delete_room.assert_awaited_once()
    screen.source.aclose.assert_awaited_once()


async def test_other_participant_and_handback_key_cannot_confirm(screen):
    screen.wire_events()
    for identity, digit in [("unrelated", "1"), (screen.identity, "#")]:
        screen.events["sip_dtmf_received"](
            SimpleNamespace(participant=SimpleNamespace(identity=identity), digit=digit)
        )
    assert not screen.result.done()


async def test_operator_resuming_while_doctor_answers_cancels_join(screen):
    screen.t.c.call["control"] = "ai"
    screen.t.c.call["status"] = "ended"
    screen.finish("confirmed")
    with pytest.raises(ControlError, match="no longer pending"):
        await screen.run("+12025550101")
    screen.t.lk.room.move_participant.assert_not_called()
    screen.t.lk.room.delete_room.assert_awaited_once()


@pytest.mark.parametrize(
    "greeting",
    [
        "Please leave your message after the tone.",
        "You've reached my voicemail.",
        "I can't take your call right now.",
        "Please call later.",
    ],
)
def test_voicemail_greetings_are_recognized(greeting):
    assert answer_screen.VOICEMAIL.search(greeting)


def test_ordinary_hello_is_not_voicemail():
    assert not answer_screen.VOICEMAIL.search("Hello, this is the doctor.")
