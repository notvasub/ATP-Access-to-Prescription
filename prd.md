# PRD: AI Insurance-Calling Assistant

## Product overview

An AI assistant that handles insurance calls for medication prior authorization on behalf of a medical practice. It speaks naturally, navigates phone menus, waits on hold, explains requests, and answers factual questions using supplied records. When the conversation becomes emotionally sensitive, contentious, or requires advocacy, it briefs an administrator or doctor and brings them onto the same live call. The human can return control to the AI after handling that exchange and rejoin later as needed.

**Core promise:** AI handles the routine conversation. People step in when needed, then hand it back.

The intended experience is a fluid, professional phone conversation without robotic scripts or repeated explanations. Natural delivery should build credibility through accurate answers and continuity.

## Problem and goal

Prior authorization takes doctors and practice staff away from patient care through paperwork, waiting, repeated explanations, and insurer back-and-forth. The goal is to reduce the time people actively spend on these calls while preserving the doctor's role in clinical decisions and advocacy. Coverage approval remains the insurer's decision.

## Parties involved

| Party | Role |
| --- | --- |
| Patient | Needs access to the prescribed medication; benefits from the practice resolving authorization barriers. |
| Practice staff | Initiates the task, supplies records, takes over when needed, returns control to the AI, and handles follow-up work. |
| AI assistant | Handles routine conversation, requests human help, follows the human exchange silently, resumes when handed control, and records next steps. |
| Insurer / PBM | Verifies coverage, reviews evidence, requests clarification, and determines authorization outcomes. |
| Doctor | Joins for advocacy or clinical judgment, returns the call to the AI with a phone control, and can rejoin as needed. |
| Pharmacy | Processes the prescription after authorization and other access requirements are satisfied. |

## Core experience

1. **Start the request.** The practice supplies the prescription, insurance details, relevant clinical records, and any existing authorization or denial information. Staff or the doctor delegates the call to the assistant.
2. **AI handles the conversation.** The assistant calls on behalf of the practice, navigates verification and hold queues, explains the request, and answers routine questions with natural pacing and context-aware responses. It can clarify a factual misunderstanding using supplied evidence. Its introduction and identity responses must be truthful and meet applicable disclosure requirements.
3. **Recognize the handoff moment.** The assistant promptly initiates human takeover when it detects frustration, escalating disagreement, emotionally sensitive discussion, or a need to persuade or argue the case. It does not wait until it lacks a factual answer. A request for a human, missing necessary information, or a need for clinical authority also triggers escalation. Administrative matters may go to practice staff.
4. **Brief and connect a human.** The assistant maintains the insurer connection and briefs the appropriate administrator or doctor on the issue, objections, and conversation so far. Once they accept, they join the same call and take over. The AI stops speaking but continues following the conversation so it retains new information and commitments. If no suitable person is available or the payer requires a scheduled review, arrange the next contact rather than continuing an argument autonomously.
5. **Return control to the AI.** After handling the specific issue, the human taps **Return to AI**. The assistant acknowledges the handback and resumes from the latest conversation context, including decisions and outstanding tasks. The human can leave their own connection or stay to monitor without ending the insurer's call. Both administrators and doctors can take over and hand back repeatedly; transitions make the current speaker clear.
6. **Capture the outcome.** The assistant records the result, reference number, outstanding requirements, and next action with an owner and due date when applicable. Outcomes include approval, additional information needed, pending review, or denial with an available review or appeal route.

## Product surfaces

- **Practice interface:** A lightweight case view with supplied records, call progress, summary, and follow-up tasks. Controls include **Start call**, **Take over**, and **Return to AI**, with a clear indicator of who currently controls the conversation.
- **Phone controls for staff and doctors:** A short briefing and a phone-accessible control surface to join, return control to the AI, or rejoin later. A lightweight mobile web view can provide these controls without a new installed app or SMS workflow; custom buttons are not assumed to appear in the phone's native call screen.
- **Case outcome:** A clear record returned to the practice. Authorization approval and actual medication access are tracked as separate milestones.

For the Impiricus challenge, present this as added value within an existing practice or Impiricus workflow. Any prototype interface demonstrates that experience; unbuilt integrations must be identified as proposed.

## Optional practice voice

Use an ElevenLabs voice clone of a consenting practice administrator to give the assistant a consistent practice voice. This may provide audible continuity when that same administrator takes over; a doctor joining remains a separate speaker. Clearly signal human takeover and preserve the identity and disclosure requirements above.

Voice enrollment requires the administrator's explicit, revocable permission and the provider's verification process. Disable the clone if permission is withdrawn; a standard licensed voice remains available. For ElevenLabs Professional Voice Cloning, the administrator creates and verifies their own clone, then shares it privately with the practice. See [ElevenLabs' requirements](https://help.elevenlabs.io/hc/en-us/articles/36842751624209-Can-I-create-a-Professional-Voice-Clone-of-someone-else-s-voice).

## MVP scope

Demonstrate one medication-authorization scenario through the sequence **AI → administrator → AI → doctor → AI**, all on the same insurer call, followed by a recorded outcome. Repatha can serve as the fictional cardiology demo case.

Show routine conversation, human takeover for resistance or a sensitive exchange, and the AI continuing follow-up after a one-tap handback. Verify that it uses information learned during human participation. Include an unavailable-human or interrupted-call fallback. Use synthetic records and consenting test participants.

The initial scope does not require rebuilding electronic prescribing, authorization forms, or a full EHR integration. It must demonstrate substantive insurance conversation, not just hold-time detection or status checking.

## Essential requirements and boundaries

- Use authorized case information; never invent clinical facts, impersonate a clinician, or independently change treatment.
- Preserve context across every takeover and handback. Only one practice-side participant speaks for the case at a time; the AI stays silent while a human has control.
- Confirm successful transfer of control before releasing a participant. A failed handback or accidental human disconnect must not silently end the insurer call or imply the AI has resumed.
- Let users intervene and make failed calls or unresolved work visible.
- Keep supporting evidence and payer statements distinguishable from AI summaries.
- Respect payer-specific submission, review, and appeal processes; do not assume every issue can be resolved on one call.
- Keep patient information separate from promotional targeting. Real deployment requires appropriate privacy safeguards, vendor agreements, and calling compliance.

## Success measures

- Less active call time for practice staff and doctors.
- Successful takeovers and handbacks, with enough context for either the human or AI to continue immediately.
- Timely recognition of conversations that need human advocacy or emotional judgment.
- Natural, accurate exchanges without forcing the payer to repeat information.
- Fewer unnecessary physician interruptions.
- Accurate case outcomes and actionable follow-up records.
- Reliable recovery when a call or handoff cannot be completed.

Time savings and approval outcomes must be measured rather than promised. The hackathon demonstration validates the interaction and technical execution; it does not establish production payer acceptance or clinical effectiveness.
