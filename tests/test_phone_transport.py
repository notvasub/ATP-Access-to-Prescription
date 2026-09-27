from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from atp.config import Settings
from atp.voice import VoiceTransport


async def test_both_phone_legs_use_private_answer_screening(monkeypatch):
    from atp import voice

    c = SimpleNamespace(
        settings=Settings(_env_file=None, plivo_phone_number="+12025550120"),
        call={"room": "same-room", "contacts": {"insurer_phone_number": "+12025550121"}},
    )
    t = VoiceTransport(c)
    screen = SimpleNamespace(run=AsyncMock())
    factory = Mock(return_value=screen)
    monkeypatch.setattr(voice, "AnswerScreen", factory)
    await t.dial()
    factory.assert_called_once_with(t, "payer", role="insurer")
    screen.run.assert_awaited_once_with("+12025550121")
    factory.reset_mock()
    screen.run.reset_mock()
    await t.dial_doctor("+12025550122", "doctor-phone-test")
    factory.assert_called_once_with(t, "doctor-phone-test")
    screen.run.assert_awaited_once_with("+12025550122")


async def test_phone_handback_removes_only_doctor_leg():
    c = SimpleNamespace(
        settings=None,
        call={"room": "same-room", "doctor_call": {"identity": "doctor-phone-test"}},
    )
    t = VoiceTransport(c)
    participants = [
        SimpleNamespace(identity=name) for name in ["agent", "payer", "doctor-phone-test", "operator"]
    ]
    room = SimpleNamespace(
        list_participants=AsyncMock(return_value=SimpleNamespace(participants=participants)),
        remove_participant=AsyncMock(),
        update_participant=AsyncMock(),
    )
    t.lk = SimpleNamespace(room=room)
    await t.set_speaker("doctor-phone-test")
    doctor_permission = room.update_participant.call_args_list[0].args[0].permission
    assert doctor_permission.can_publish_data  # Phone DTMF remains available.
    await t.set_speaker(None)
    assert room.remove_participant.call_count == 1
    assert room.remove_participant.call_args.args[0].identity == "doctor-phone-test"


@pytest.mark.parametrize("identity", ["payer", "agent", "", "doctor-phone-stale"])
async def test_doctor_removal_rejects_every_other_call_leg(identity):
    c = SimpleNamespace(
        settings=None,
        call={"room": "same-room", "doctor_call": {"identity": "doctor-phone-current"}},
    )
    t = VoiceTransport(c)
    t.lk = SimpleNamespace(room=SimpleNamespace(remove_participant=AsyncMock()))
    with pytest.raises(ValueError):
        await t.remove_doctor(identity)
    t.lk.room.remove_participant.assert_not_awaited()
