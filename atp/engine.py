"""Authoritative call state. All control changes are serialized on one event loop."""

import asyncio
import copy
import re
import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from .config import Settings
from .contacts import load_contacts
from .pitch import CASE as PITCH_CASE
from .pitch import GREETING, HANDBACK
from .store import Store

TERMINAL = {"ended", "failed"}
HUMANS = {"administrator", "doctor"}
HESITATIONS = {"um", "uh", "hmm", "erm", "er"}
ACKNOWLEDGMENTS = {
    "mhm",
    "uh huh",
    "yeah",
    "yes",
    "okay",
    "ok",
    "right",
    "yes that's right",
    "yeah that's right",
}
UNFINISHED_ENDINGS = {
    "and",
    "but",
    "because",
    "or",
    "so",
    "the",
    "a",
    "an",
    "to",
    "for",
    "with",
    "about",
    "is",
    "was",
    "has",
    "have",
}


def speech_words(text):
    return re.sub(r"[^\w' ]", " ", text.lower().replace("’", "'")).split()


def unfinished_phrase(text):
    words = speech_words(text)
    return text.rstrip().endswith(("...", "…", "-", "—")) or (
        bool(words) and words[-1] in UNFINISHED_ENDINGS and not text.rstrip().endswith("?")
    )


FIELDS = {
    "member_id",
    "patient_name",
    "provider",
    "medication",
    "authorization_status",
    "reference_number",
    "requirements",
    "approval_window",
    "pharmacy",
    "next_action",
    "owner",
    "due_date",
    "medication_access",
}


class ControlError(Exception):
    def __init__(self, message: str, status: int = 409):
        self.message, self.status = message, status
        super().__init__(message)


class Fact(BaseModel):
    field: str
    value: str = Field(max_length=1000)
    evidence_turn_ids: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    reply: str = Field(description="Short spoken response, or empty when no response is appropriate")
    escalation_role: Literal["none", "administrator", "doctor"] = "none"
    reason: str = ""
    facts: list[Fact] = Field(default_factory=list)
    end_call: bool = False
    dtmf: str = ""


class Coordinator:
    def __init__(self, settings: Settings, store: Store, transport_factory=None):
        self.settings, self.store = settings, store
        self.transport_factory = transport_factory
        self.call = None
        self.transport = None
        self.lock = asyncio.Lock()
        self.listeners: set[asyncio.Queue] = set()
        self.tasks: set[asyncio.Task] = set()
        self.reply_task = None
        self.turn_tasks: dict[str, asyncio.Task] = {}
        self.epoch = 0
        self.request_results = {}
        self.session_participants = {}
        self.closing = False
        self.ready_checks = {}
        self.extract_sequence = 0
        self.doctor_task = None
        self.notify_doctor = None
        self.notify_completion = None
        self.handoff_resume = False
        self.contacts = load_contacts(store, settings)

    def spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def recover(self):
        for call in self.store.calls():
            if call["status"] not in TERMINAL:
                call.update(
                    status="failed",
                    control="paused",
                    error="Backend restarted. Call interrupted.",
                    ended_at=time.time(),
                )
                self.store.put("call:" + call["id"], call)
        if not self.call:
            calls = self.store.calls()
            self.call = calls[0] if calls else None

    def snapshot(self, private=False):
        call = copy.deepcopy(self.call) if self.call else None
        if call:
            update = call.get("docupdates") or {}
            call["approval_notification_status"] = update.get("notification_status", "")
        if call and not private:
            call.pop("briefing", None)
            call.pop("request_results", None)
            call.pop("contacts", None)
            call.pop("doctor_call", None)
            call.pop("docupdates", None)
        return call

    def emit(self, kind="state", **payload):
        if not self.call:
            return
        self.call["sequence"] += 1
        if kind != "partial":
            self.store.put("call:" + self.call["id"], self.call)
        event = {"type": kind, "call_id": self.call["id"], "sequence": self.call["sequence"], **payload}
        for queue in tuple(self.listeners):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def start(self, mode="phone", scenario="standard"):
        async with self.lock:
            if self.closing:
                raise ControlError("The previous call is still disconnecting. Try again in a moment.")
            if self.call and self.call["status"] not in TERMINAL:
                raise ControlError("A call is already active.")
            if not self.settings.app_demo_password:
                raise ControlError("Set APP_DEMO_PASSWORD before starting a call.", 503)
            self.request_results = {}
            self.handoff_resume = False
            self.session_participants = {}
            self.closing = False
            self.epoch += 1
            call_id = uuid.uuid4().hex[:12]
            self.call = {
                "id": call_id,
                "room": "atp-" + call_id,
                "mode": mode,
                "scenario": scenario,
                "status": "starting",
                "control": "ai",
                "revision": 0,
                "sequence": 0,
                "created_at": time.time(),
                "answered_at": None,
                "ended_at": None,
                "transcript": [],
                "facts": {},
                "events": [],
                "participants": {},
                "briefing": None,
                "error": None,
                "agent_status": "connecting",
                "case": copy.deepcopy(PITCH_CASE) if scenario == "pitch" else self.store.get("case"),
                "contacts": dict(self.contacts),
                "doctor_call": None,
            }
            self.emit()
            self.spawn(self._connect(call_id))
            self.spawn(self._deadline(call_id))
            return self.snapshot(True)

    async def _connect(self, call_id):
        try:
            if self.transport_factory:
                self.transport = self.transport_factory(self)
            else:
                from .voice import VoiceTransport

                self.transport = VoiceTransport(self)
            await self.transport.start()
            if self.call["id"] != call_id or self.call["status"] in TERMINAL:
                return
            self.call["status"] = "dialing" if self.call["mode"] == "phone" else "active"
            self.call["agent_status"] = "listening"
            self.emit()
            if self.call["mode"] == "phone":
                await self.transport.dial()
            if self.call["status"] not in TERMINAL:
                self.call["status"] = "active"
                self.call["answered_at"] = time.time()
                self.emit()
                if self.call["mode"] == "phone":
                    self.greet()
                elif self.call["transcript"] and self.call["transcript"][-1]["speaker"] == "payer":
                    self.schedule_reply()
        except asyncio.CancelledError:
            raise
        except ControlError as exc:
            await self.fail(exc.message)
        except Exception as exc:
            await self.fail(
                "Connection failed (" + type(exc).__name__ + "). Check readiness and SIP configuration."
            )

    async def _deadline(self, call_id):
        await asyncio.sleep(min(max(self.settings.demo_max_call_seconds, 30), 600))
        if self.call and self.call["id"] == call_id and self.call["status"] not in TERMINAL:
            await self.end("Demo time limit reached.")

    async def fail(self, message):
        if not self.call or self.call["status"] in TERMINAL:
            return
        await self.end(message, failed=True)

    async def end(self, reason="Call ended by operator.", failed=False):
        async with self.lock:
            if not self.call or self.call["status"] in TERMINAL:
                return
            self.closing = True
            await self._interrupt()
            self.call.update(
                status="failed" if failed else "ended",
                control="paused",
                ended_at=time.time(),
                agent_status="offline",
                error=reason if failed else self.call["error"],
            )
            if self.call.get("doctor_call") and self.call["doctor_call"]["status"] in {
                "calling",
                "screening",
                "connected",
            }:
                self.call["doctor_call"]["status"] = "ended"
            self.call["revision"] += 1
            self.call["events"].append({"time": time.time(), "text": reason})
            self.emit()
            completed_call = copy.deepcopy(self.call)
            completed_call["approval_transcript_incomplete"] = bool(
                getattr(self.transport, "pending_transcripts", set())
            )
        current = asyncio.current_task()
        pending = [task for task in self.tasks if task is not current]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        try:
            # Review the frozen transcript while RTC cleanup runs, rather than after it.
            if (
                self.notify_completion
                and not failed
                and reason not in {"Application shutting down.", "Demo time limit reached."}
            ):
                self.notify_completion(completed_call)
        finally:
            try:
                if self.transport:
                    await self.transport.close()
            finally:
                self.closing = False

    async def _interrupt(self):
        self.epoch += 1
        task = self.reply_task
        self.reply_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.transport:
            self.transport.interrupt()
        if self.call:
            self.call["agent_status"] = "listening"

    async def control(self, role: str, action: str, request_id: str, revision: int, identity="", digits=""):
        if not self.call or self.call["status"] in TERMINAL:
            raise ControlError("No active call.")
        if role not in {"operator", *HUMANS}:
            raise ControlError("This role cannot control the call.", 403)
        key = (role, identity, request_id)
        async with self.lock:
            if self.call["status"] in TERMINAL or self.closing:
                raise ControlError("No active call.")
            if self.call["status"] not in {"active", "dialing"} and action != "end":
                raise ControlError("Audio is still connecting.")
            if key in self.request_results:
                return self.snapshot(True)
            if revision != self.call["revision"]:
                raise ControlError("Call state changed. Refresh and try again.")
            if action == "takeover":
                if role not in HUMANS:
                    raise ControlError("Join as administrator or doctor to take over.", 403)
                if self.call["control"] in HUMANS and self.call["controller_identity"] != identity:
                    raise ControlError("Another person controls this call. They must hand back first.")
                if identity not in self.call["participants"]:
                    raise ControlError("Connect audio before taking over.")
                await self._interrupt()
                self.call["control"] = "resuming"
                await self._switch_speaker(identity)
                self.call.update(control=role, controller_identity=identity, briefing=None)
            elif action in {"handback", "unavailable"}:
                if action == "unavailable" and role != "operator":
                    raise ControlError("Only the operator can mark a person unavailable.", 403)
                if self.call["control"] in HUMANS or (
                    self.call["control"] == "paused" and self.call.get("controller_identity")
                ):
                    if role != "operator" and self.call.get("controller_identity") != identity:
                        raise ControlError("Only the current speaker may hand back.", 403)
                elif role != "operator":
                    raise ControlError("There is no human turn to hand back.")
                await self._interrupt()
                self.call["control"] = "resuming"
                self.emit()
                # Allow a server-VAD final transcript to arrive before resuming.
                try:
                    if self.call.get("controller_identity"):
                        await self.transport.flush_transcripts(self.call["controller_identity"])
                except Exception:
                    self.call.update(
                        control="paused",
                        error="Last words are still transcribing. Pause speaking, then press # again or retry Return to AI.",
                    )
                    self.call["revision"] += 1
                    self.emit()
                    raise ControlError(self.call["error"], 503)
                await self._switch_speaker(None)
                self.call.update(control="ai", controller_identity=None, briefing=None, error=None)
                if self.call.get("doctor_call"):
                    self.call["doctor_call"]["status"] = "returned"
            elif action == "pause":
                if role != "operator":
                    raise ControlError("Only the operator can pause the call.", 403)
                await self._interrupt()
                self.call["control"] = "paused"
                await self._switch_speaker(None)
            elif action == "dtmf":
                if role != "operator":
                    raise ControlError("Only the operator can use the keypad.", 403)
                import re

                if not re.fullmatch(r"[0-9*#]{1,12}", digits):
                    raise ControlError("Use 1–12 digits, * or #.", 422)
                await self.transport.dtmf(digits)
            elif action == "end":
                if role != "operator":
                    raise ControlError("Only the operator can end the insurer call.", 403)
            else:
                raise ControlError("Unknown action.", 422)
            self.call["revision"] += 1
            self.request_results[key] = True
            self.call["events"].append({"time": time.time(), "text": f"{role.capitalize()}: {action}"})
            self.emit()
        if action == "end":
            await self.end()
        elif action == "unavailable":
            self.schedule_reply(
                "The requested human is unavailable. Tell the payer courteously and arrange the next contact or scheduled review, including owner and due date. Do not invent evidence or continue advocacy."
            )
        elif action == "handback":
            self.handoff_resume = True
            self.schedule_reply(
                "The human has handed control back. Acknowledge briefly, use new information, and continue the outstanding task.",
                decision=Decision(reply=HANDBACK) if self.call.get("scenario") == "pitch" else None,
            )
        return self.snapshot(True)

    async def _switch_speaker(self, identity):
        try:
            await self.transport.set_speaker(identity)
        except Exception:
            self.call.update(
                control="paused",
                error="Audio transfer was not confirmed. Reconnect audio or retry from the operator screen.",
            )
            self.call["revision"] += 1
            self.emit()
            raise ControlError(self.call["error"], 503)

    async def participant(self, identity, connected, disconnect_reason="UNKNOWN_REASON"):
        if not self.call or self.closing:
            return
        if connected:
            role = self.session_participants.get(identity, "payer" if identity == "payer" else "unknown")
            self.call["participants"][identity] = {"role": role, "connected": True}
            if identity == "payer" and self.call["mode"] == "browser" and not self.call["transcript"]:
                self.greet()
        else:
            self.call["participants"].pop(identity, None)
            if identity == "payer" or identity.startswith("doctor-phone-"):
                label = "Insurer" if identity == "payer" else "Doctor"
                self.call["events"].append(
                    {"time": time.time(), "text": f"{label} connection closed: {disconnect_reason}."}
                )
            if identity == "payer":
                await self.end("The insurer disconnected.")
                return
            if self.call.get("controller_identity") == identity:
                async with self.lock:
                    if self.call.get("controller_identity") != identity or self.call["status"] in TERMINAL:
                        return
                    await self._interrupt()
                    self.call.update(
                        control="paused",
                        error="The controlling human disconnected. Operator action required.",
                    )
                    self.call["revision"] += 1
        self.emit()

    async def transcript(self, identity, text, final):
        if not self.call or self.call["status"] in TERMINAL or not text.strip():
            return
        role = self.session_participants.get(identity, "payer" if identity == "payer" else "unknown")
        if role == "unknown":
            return
        words = speech_words(text)
        normalized = " ".join(words)
        acknowledgment = normalized in ACKNOWLEDGMENTS or normalized in HESITATIONS
        if not final:
            self.emit("partial", speaker=role, identity=identity, text=text)
            if role == "payer" and self.call["control"] == "ai":
                speaking = self.call["agent_status"] == "speaking"
                # A resumed human turn invalidates a queued or in-flight answer.
                # Short acknowledgments during playback do not seize the floor.
                if not speaking or (
                    not acknowledgment
                    and (len(words) >= 3 or words[:1] in (["stop"], ["wait"], ["no"], ["sorry"]))
                ):
                    await self._interrupt()
                    self.emit()
            return
        turn = {
            "id": uuid.uuid4().hex[:10],
            "speaker": role,
            "identity": identity,
            "text": text,
            "time": time.time(),
            "interrupted": False,
        }
        self.call["transcript"].append(turn)
        self.emit("partial", speaker=role, identity=identity, text="")
        self.emit("transcript", turn=turn)
        if role == "payer" and self.call["control"] == "ai" and self.call["status"] == "active":
            if acknowledgment and self.call["agent_status"] == "speaking":
                return
            if words and all(word in HESITATIONS for word in words):
                await self._interrupt()
                self.emit()
                return
            delay = self.settings.turn_end_delay_seconds
            if unfinished_phrase(text):
                delay = max(delay, self.settings.incomplete_turn_delay_seconds)
            self.schedule_reply(delay=delay)
        elif self.call["control"] in HUMANS:
            # Extract evidence silently; this path can never publish speech.
            self.spawn(self._extract())

    def add_agent_turn(self, text, interrupted=False):
        if not text:
            return
        turn = {
            "id": uuid.uuid4().hex[:10],
            "speaker": "ai",
            "identity": "agent",
            "text": text,
            "time": time.time(),
            "interrupted": interrupted,
        }
        self.call["transcript"].append(turn)
        self.emit("transcript", turn=turn)

    def greet(self):
        self.schedule_reply(
            "The insurer has answered. Introduce yourself as the practice's AI assistant and explain the call objective.",
            decision=Decision(reply=GREETING) if self.call.get("scenario") == "pitch" else None,
        )

    def schedule_reply(self, instruction="", decision=None, delay=0.25):
        if self.reply_task and not self.reply_task.done():
            self.reply_task.cancel()
            if self.transport:
                self.transport.interrupt()
        self.epoch += 1
        epoch = self.epoch
        self.reply_task = self.spawn(self._reply(epoch, instruction, decision, delay))

    def apply_facts(self, facts, call_id):
        if not self.call or self.call["id"] != call_id:
            return
        turns = {t["id"]: t for t in self.call["transcript"] if t["speaker"] != "ai"}
        for fact in facts:
            ids = [i for i in fact.evidence_turn_ids if i in turns]
            if fact.field not in FIELDS or not ids:
                continue
            self.call["facts"][fact.field] = {
                "value": fact.value,
                "evidence_turn_ids": ids,
                "source": "payer" if all(turns[i]["speaker"] == "payer" for i in ids) else "human",
                "updated_at": time.time(),
            }
        self.emit()

    async def _extract(self):
        call_id = self.call["id"]
        self.extract_sequence += 1
        sequence = self.extract_sequence
        try:
            decision = await self.transport.decide(
                "Extract facts only. reply must be empty. Do not escalate or end the call."
            )
            if (
                self.call
                and self.call["id"] == call_id
                and self.call["status"] not in TERMINAL
                and sequence == self.extract_sequence
                and self.call["control"] in HUMANS
            ):
                self.apply_facts(decision.facts, call_id)
        except Exception:
            pass  # Extraction never interrupts an active human conversation.

    async def _reply(self, epoch, instruction, decision=None, delay=0.25):
        try:
            await asyncio.sleep(delay)
            if epoch != self.epoch or self.call["control"] != "ai":
                return
            self.call["agent_status"] = "thinking"
            self.emit()
            if self.handoff_resume:
                instruction += " The human just finished participating. Your next turn must continue with the insurer using the human's latest contribution. If something is unclear, ask the insurer a concise follow-up. Do not immediately recall the doctor for the same issue."
            doctor_unavailable = (self.call.get("doctor_call") or {}).get("status") == "failed"
            if doctor_unavailable:
                instruction += " The doctor could not be reached and did not participate. Arrange a callback with the insurer. Do not claim the doctor answered, and do not request another doctor call; only the operator may retry."
            decision = decision or await self.transport.decide(instruction)
            if doctor_unavailable and decision.escalation_role != "none":
                decision = decision.model_copy(
                    update={
                        "escalation_role": "none",
                        "end_call": False,
                        "reply": "Our doctor is unavailable right now. Could we arrange a callback?",
                    }
                )
            if self.handoff_resume and decision.escalation_role != "none":
                decision = decision.model_copy(
                    update={
                        "escalation_role": "none",
                        "end_call": False,
                        "reply": "Thank you. Could you confirm the next step based on what our doctor just discussed?",
                    }
                )
            if epoch != self.epoch or self.call["control"] != "ai" or self.call["status"] in TERMINAL:
                return
            self.apply_facts(decision.facts, self.call["id"])
            if decision.dtmf:
                import re

                if re.fullmatch(r"[0-9*#]{1,12}", decision.dtmf):
                    await self.transport.dtmf(decision.dtmf)
            if decision.escalation_role != "none":
                self.call.update(
                    control="handoff_pending",
                    briefing={
                        "role": decision.escalation_role,
                        "reason": decision.reason,
                        "summary": decision.reason,
                        "requested_at": time.time(),
                    },
                )
                self.call["revision"] += 1
                self.call["events"].append(
                    {"time": time.time(), "text": "Human requested: " + decision.escalation_role}
                )
                if self.call["mode"] == "phone":
                    self.request_doctor()
            if decision.reply:
                self.call["agent_status"] = "speaking"
                self.emit()
                await self.transport.speak(decision.reply, epoch)
            if epoch != self.epoch:
                return
            self.call["agent_status"] = "listening"
            self.emit()
            self.handoff_resume = False
            if decision.end_call and decision.escalation_role == "none":
                await self.end("Conversation completed.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.call and self.call["status"] not in TERMINAL:
                self.call.update(
                    control="paused",
                    agent_status="offline",
                    error="Voice service interrupted ("
                    + type(exc).__name__
                    + "). Take over or retry handback.",
                )
                self.call["revision"] += 1
                self.emit()

    def request_doctor(self):
        if not self.call or self.call["status"] in TERMINAL:
            raise ControlError("No active call.")
        if self.doctor_task and not self.doctor_task.done():
            raise ControlError("The doctor is already being called.")
        previous = self.call.get("doctor_call") or {}
        if self.call["control"] == "ai" and previous.get("status") == "failed":
            if self.reply_task and not self.reply_task.done():
                self.reply_task.cancel()
            self.epoch += 1
            self.transport.interrupt()
            self.call.update(control="handoff_pending", briefing=copy.deepcopy(previous.get("briefing")))
            self.call["revision"] += 1
        if self.call["control"] != "handoff_pending":
            raise ControlError("ATP has not requested a doctor.")
        identity = "doctor-phone-" + uuid.uuid4().hex[:8]
        attempt = {
            "identity": identity,
            "status": "calling",
            "notification_provider": "slack",
            "notification_status": "pending",
            "error": None,
            "briefing": copy.deepcopy(self.call.get("briefing")),
        }
        self.call["doctor_call"] = attempt
        self.session_participants[identity] = "doctor"
        self.emit()
        self.doctor_task = self.spawn(self._call_doctor(self.call["id"], attempt))

    async def _call_doctor(self, call_id, attempt):
        identity = attempt["identity"]
        try:
            number = self.call["contacts"].get("doctor_phone_number")
            if not number:
                raise ControlError("Set the doctor's phone number in Call destinations.")
            if self.notify_doctor:
                self.spawn(self.notify_doctor(self.call, attempt))
            else:
                attempt["notification_status"] = "unavailable"
            await self.transport.dial_doctor(number, identity)
            if self.call["id"] != call_id or self.closing:
                return
            if self.call["control"] != "handoff_pending":
                await self.transport.remove_doctor(identity)
                attempt["status"] = "cancelled"
                self.emit()
                return
            for _ in range(30):
                if identity in self.call["participants"]:
                    break
                await asyncio.sleep(0.1)
            await self.control("doctor", "takeover", identity, self.call["revision"], identity)
            attempt["status"] = "connected"
            self.emit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.call["id"] == call_id and self.call["status"] not in TERMINAL:
                attempt["status"] = "failed"
                attempt["error"] = (
                    exc.message
                    if isinstance(exc, ControlError)
                    else "Doctor call was not connected. Check recipient verification and call capacity, or retry."
                )
                try:
                    await self.transport.remove_doctor(identity)
                except Exception:
                    pass
                async with self.lock:
                    if self.call["id"] != call_id or self.call["status"] in TERMINAL:
                        return
                    if self.call["control"] == "handoff_pending":
                        await self._interrupt()
                        self.handoff_resume = False
                        self.call.update(control="ai", controller_identity=None, briefing=None)
                        self.call["revision"] += 1
                        self.call["events"].append({"time": time.time(), "text": attempt["error"]})
                        self.schedule_reply(
                            decision=Decision(
                                reply="I couldn't reach our doctor, so I've ended that call attempt. Could we arrange a callback?"
                            )
                        )
                    self.emit()

    async def phone_handback(self, identity):
        if not self.call or self.call["status"] in TERMINAL:
            return
        if self.call.get("controller_identity") != identity or not identity.startswith("doctor-phone-"):
            return
        try:
            await self.control("doctor", "handback", uuid.uuid4().hex, self.call["revision"], identity)
        except ControlError as exc:
            self.call["error"] = exc.message
            self.emit()
