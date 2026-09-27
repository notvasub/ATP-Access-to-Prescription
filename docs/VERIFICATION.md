# ATP verification — September 26, 2026

## Passed

- `make test`: 13 unit/API tests, Ruff, TypeScript compilation, Vite production build.
- Provider preflight: OpenAI configured model, selected ElevenLabs Viraj voice, LiveKit room API, Plivo caller number, matching outbound SIP trunk.
- Real telephone call: Plivo/LiveKit connected to the configured consenting recipient; their speech was transcribed. The user confirmed ATP was audible. The recipient disconnected normally. This test exposed missing captions for interrupted AI speech; aligned word timestamps now address that, with a regression test.
- Real-provider audio loop: generated Viraj speech published to LiveKit, transcribed by Scribe, answered by OpenAI, and played through ElevenLabs.
- Full real-provider handoff rehearsal: AI → administrator → AI → doctor → AI, with three RTC participants and the same room throughout. Both human turns were transcribed while AI stayed silent. ATP reused the administrator's fax tracking number and the doctor's request for a clinical review tomorrow.
- Backend tests: exclusive control, stale/idempotent requests, interrupting pending AI, failure to transfer audio, accidental human disconnect, unavailable-human fallback, payer disconnect, restart recovery, cleanup/start race, evidence provenance, access roles, CSRF header, invite replay, private WebSocket snapshots, interrupted-speech captions.
- Browser inspection: operator workspace, navy presentation surface, mobile administrator layout at 390×844, authenticated HTTPS access through the temporary Cloudflare tunnel.
- Live WebSocket authentication without credentials in URL query strings; saved history and JSON export endpoints.
- All ATP test rooms were closed after verification.

## Still requires pitch-device rehearsal

Actual Safari microphone permission, audio routing, phone lock/background behavior, and acoustic feedback depend on the physical devices. Keep mobile browsers in the foreground and use headphones. The repeated handoff check used RTC test participants; the separate PSTN check confirmed real telephone audio. A full multi-person PSTN rehearsal on the pitch devices has not yet been performed.

The build emits a bundle-size advisory because the voice client is included in the main JavaScript bundle. Compilation succeeds. This prototype is not a production healthcare system; see README for scope and operating limits.


## Updated two-number workflow

- Separate, locally persisted insurer and doctor destination settings, seeded from `.env` and editable in the operator UI.
- 24 tests now pass, including automatic doctor dialing/notification dispatch, no-answer handling, stale answer cancellation, phone-only control sessions, separate SIP destinations, doctor-only disconnect, SMS error handling, and the immediate-recall guard.
- Real call on both configured phones: AI introduced itself without operator speech, insurer requested clinical help, ATP rang the doctor and joined that phone to the same room. Pressing # returned control to AI and preserved the insurer call.
- SMS delivery did **not** succeed. Plivo's HTTP 400 response states that the US long-code source is not mapped to a 10DLC campaign. This is an external account setup blocker, reported in the UI.
- The real test exposed a repeat escalation immediately after handback. The first post-handback turn now continues with the insurer instead of immediately repeating the doctor request; this fix has an automated regression test and needs a subsequent live rehearsal.
- The greeting and audio path were independently verified again with real LiveKit, ElevenLabs and OpenAI.

## Doctor voicemail fix

- 39 unit/API tests pass; Ruff and the TypeScript/Vite build pass. Tests cover 30-second ringing configuration, confirmation before room transfer, voicemail/no-confirmation rejection, cancellation cleanup, spoken insurer fallback, no automatic redial, and explicit operator retry.
- Doctor calls now start in a private screening room. Press 1 confirms a human answer; # still hands back after joining. No screening audio or transcript enters the insurer conversation.
- `scripts/smoke_screening.py` passed with real LiveKit and ElevenLabs/Scribe: a synthetic RTC doctor sent 1, moved rooms, and sent # to return control. A second synthetic RTC participant played a voicemail greeting; Scribe detected it, the doctor attempt ended, and ATP spoke the unavailable fallback. The SIP dial API was replaced by RTC participants, so this check made no telephone calls or SMS sends.
- The new carrier ringing limit and physical phone keypad flow still need a phone rehearsal. A carrier may forward to voicemail before 30 seconds; ATP cannot override that forwarding policy. The private confirmation prevents that answer from being treated as a doctor joining.

## Slack notification setup

- Created the private `#atp-demo` channel in the user-selected **ATP** workspace and installed the ATP app with only the `incoming-webhook` permission for that channel.
- Saved `SLACK_WEBHOOK_URL` privately in the ignored `.env`; no secret is included in logs, source, browser snapshots shown to the user, or this document.
- Replaced Plivo SMS sending/polling with Slack Block Kit notifications for both doctor escalation briefings and confirmed completion updates. Buttons open the existing scoped call-control and DocUpdates pages. This does not add Slack chat commands.
- Sent one explicit setup test message and verified it visibly in the channel. Slack returned `200 ok`. Channel notifications are set to all new posts; the user's Slack account was showing notifications snoozed.
- `make test`: **69 tests passed**, Ruff passed, TypeScript and Vite production build passed. Added checks for Slack failures/timeouts, secret redaction, mention escaping, approval gating, and doctor-control links.
- Restarted the local app after confirming no call was active. No phone call or SMS was sent during this setup.

## Scripted pitch mode

- `make test`: **74 tests passed**, Ruff passed, TypeScript and Vite production build passed.
- Added a separately selected pitch scenario with the fictional Morgan Ellis / Repatha case, concise opening and handback, routine-question handling, and frustration/clinical escalation. The source case remains unchanged; neither the doctor's LDL statement nor an approval is preloaded.
- `scripts/smoke_pitch.py` completed the full conversation in **63.4 seconds** with real LiveKit audio, ElevenLabs speech generation/recognition, OpenAI decisions, and final approval review. It exercised neutral treatment-history answering, frustration escalation, press-1 screening, doctor speech, # handback, automatic ending, and verified reference DEMO84921 in the final Slack payload.
- This automated run substituted RTC actors for both telephone legs and captured Slack delivery locally. It made no telephone calls and posted no Slack messages. Physical phone ringing and live Slack delivery are not included in the measured time; a timed rehearsal on the pitch phones remains necessary.
- Final approval review begins while call transport cleanup runs. Slack messages now include verified patient, medication, authorization reference, coverage, next step, and the DocUpdates link. Approval still requires explicit payer evidence.

## Phone handback investigation and hardening

- In the reported call, doctor handback completed and ATP resumed; the insurer disconnected about four seconds later. Plivo recorded the doctor hangup as customer-initiated (3010) and the insurer hangup as carrier-initiated (3000). This identifies the terminating side, not the underlying cause; the original unexpected disconnect remains unexplained.
- A subsequent authorized two-phone test exposed a separate transcription stall during # handback. Operator recovery removed only the doctor, ATP resumed, and the insurer remained connected until the user intentionally ended the test. The user confirmed that final hangup was intentional.
- Handback now flushes only the returning human's transcription, so insurer speech cannot block it. If the doctor's final words still time out, the same doctor can pause speaking and retry #. Previously the paused state incorrectly rejected that retry.
- Doctor removal now rejects any identity other than the current doctor phone participant. Disconnect events retain LiveKit's reason for both phone legs to help diagnose future drops.
- **81 tests passed**, including doctor-only removal, preserved insurer participation after doctor departure, transcription isolation, and retry after a transcription timeout. Ruff passed. No carrier-disconnect fix is claimed without reproducing the original cause.
- Updated real-service automated pitch rehearsal passed in **67.3 seconds**, including doctor # handback and continued insurer speech through verified approval. Both phone legs were RTC actors and Slack delivery was captured locally; no additional phone calls or Slack messages were sent by that rehearsal.

## Conversational pauses

- Increased Scribe's silence threshold from 0.7 to 1.3 seconds; added a cancellable 0.7-second turn-ending delay, extended to 1.8 seconds for obvious unfinished phrases. These are optional validated settings, not new API credentials.
- Resumed partial speech now cancels queued and in-flight model replies, not only audio already playing. Standalone hesitations do not trigger an answer; short acknowledgments during playback do not interrupt ATP. Explicit "wait" and "stop" still interrupt.
- **86 tests passed**, Ruff passed, and TypeScript/Vite build passed. Regression tests cover mid-turn continuation, cancellation during model inference, hesitations, unfinished phrases, and acknowledgment versus interruption.
- `scripts/smoke_pauses.py` passed using real LiveKit, ElevenLabs TTS/Scribe, and OpenAI: the synthetic payer paused for 0.9 seconds inside a sentence, ATP did not begin speaking during the pause or continuation, both halves were transcribed, then ATP answered. No telephone call or Slack message was sent. Variable human/phone audio still needs listening checks; this is a measured pause test, not a guarantee of perfect turn detection.

## Insurer voicemail screening

- Extended the existing private doctor screening to the insurer through shared `AnswerScreen` logic. Both destinations ring for up to 30 seconds and must press 1 within 10 seconds after answering. The user selected this confirmation flow for the insurer. Carrier forwarding can still happen sooner.
- Insurer voicemail and unconfirmed answers receive a short generic goodbye and disconnect without the authorization greeting, case details, transcript contamination, doctor escalation, or approval notification. The operator sees the specific screening failure. No automatic redial occurs.
- **96 tests passed**, Ruff passed, and the frontend build passed. Both roles exercise confirmation, voicemail/no-confirmation rejection, no answer, cancellation cleanup, wrong-participant DTMF rejection, and stale join prevention.
- `scripts/smoke_screening.py` passed all four real-service paths: insurer press-1 acceptance and greeting, insurer voicemail rejection, doctor press-1 acceptance and # handback, and doctor voicemail rejection with insurer fallback. LiveKit and ElevenLabs/Scribe were real; RTC actors replaced the telephone dial API. No real phone calls or Slack messages were sent.

## Richer clinical demo conversation

- Added a separate fictional pitch chart with inherited high cholesterol, LDL 260 → 190 mg/dL, and dated atorvastatin/ezetimibe trials. The saved source case is not overwritten. All added values and dates are authored demo facts. Adherence verification and maximally tolerated therapy remain unconfirmed until the live doctor attests.
- Replaced the one-sentence/18-word cap with responsive one- or two-sentence answers. The specifically requested short treatment-history answer is preserved. ATP answers the first factual objection and asks what is missing; expressed frustration and a demand for clinical responsibility trigger the doctor without an explicit transfer command.
- The revised full real-service rehearsal completed in **96.3 seconds**, exercising both press-1 screens, treatment history, the lab-evidence exchange, implicit clinical escalation, doctor attestation, # handback, and verified final approval. RTC actors substituted for both phone legs and Slack delivery was captured locally. Actual ringing and live Slack delivery are not included; 90 seconds remains a target rather than a guarantee.
- After that run, narrowed the general lab answer to the LDL trend without unsolicited dates. A real-model check returned “LDL fell from 260 to 190 mg/dL after those treatment trials. What else does your reviewer need?” and then escalated the frustrated follow-up with a briefing covering the diagnosis, timeline, labs, and missing attestation. The final wording has not been timed through another full phone rehearsal.
- **96 tests passed**, Ruff passed, TypeScript/Vite build passed. Updated source-case isolation coverage, rehearsal cues, and the pitch script to match the richer chart and the doctor's new contribution.
