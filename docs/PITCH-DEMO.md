# ATP: 90-second live pitch demo

Select **Pitch demo · 90-second target** (enabled by default) and click **Start insurer call**. The mode uses the fictional Morgan Ellis / Repatha case without overwriting the saved source case. It answers routine questions, explains the supporting evidence when challenged, and escalates on frustration or a request for clinical judgment. Approval is never preloaded or triggered by a timer.

Before the clock: verify both destination numbers, run Connection check, open the presentation view and ATP Slack channel, enable phone/Slack notifications, and have both phone keypads ready. Use headphones or earpieces on the phones; play the conference audio through only one laptop/PA output to avoid feedback. Keep the laptop awake and the HTTPS tunnel running.

Tell the audience: **“This is a live call using a fictional patient and a simulated insurer.”**

| Beat | Actor | Line / action |
|---|---|---|
| Connect | Operator / insurer | Start insurer call; answer promptly and press **1**. |
| Establish the case | ATP | Introduces itself and Morgan's familial hypercholesterolemia—an inherited high-cholesterol condition. |
| Treatment history | Insurer | “I have the case. What treatment history was submitted?” |
| Answer directly | ATP | “The supplied chart documents prior trials of atorvastatin and ezetimibe.” |
| First objection | Insurer | “Those trials alone aren't enough. What do the labs show?” |
| Explain and clarify | ATP | Explains the documented LDL change from 260 to 190 mg/dL and asks what criterion or attestation is still needed. It does not escalate this routine evidence question. |
| Frustration / clinical boundary | Insurer | “We keep going in circles. I can't approve this without someone taking clinical responsibility.” |
| Escalate | ATP / doctor | ATP identifies the need for a prescriber, posts a Slack briefing, and calls the doctor. Doctor answers and presses **1**. |
| Resolve the objection | Doctor | “Dr. Chen here. I verified adherence. These are Morgan's maximally tolerated therapies, and LDL remains 190. I recommend proceeding with Repatha.” Pause a second, then press **#**. |
| Resume | ATP | “Thank you. Can you confirm the final authorization decision?” |
| Final decision | Insurer | “Morgan Ellis's Repatha authorization is approved for twelve months. Reference D E M O, eight four nine two one. The pharmacy can process it. That completes the case. Goodbye.” |
| Deliver | ATP / operator | ATP acknowledges and ends the call. Final review verifies the payer's approval, then Slack says **Your DocUpdate has been updated**. Click **View in DocUpdate** to see the result. |

The chart now contains a **fictional** baseline LDL of 260 mg/dL on April 24, atorvastatin starting May 1, ezetimibe added June 1, and follow-up LDL of 190 mg/dL on August 24, 2026. No doses, intolerance history, adherence verification, or maximal-tolerance attestation are supplied for those trials. The doctor's live contribution is the clinical attestation, rather than repeating a lab number the AI already knows. These dates and values are authored demo facts, not medical evidence about a real patient. The general condition description follows [CDC's description of familial hypercholesterolemia](https://www.cdc.gov/heart-disease-family-history/about/about-familial-hypercholesterolemia.html).

Read the reference as individual letters and digits. Let each speaker finish. ATP can answer follow-up questions about the diagnosis, labs, and documented timeline; these are cues rather than a rigid sequence. Let ATP end after goodbye so final transcription and approval review can complete. A denial or deferral must remain a denial or deferral.

Closing line: **“ATP handled the case review and the first objection. The doctor stepped in for the clinical attestation—and delivered the authorization details straight to Slack.”**

The 90-second duration is a rehearsal target, not a forced cutoff. Carrier ringing and network latency still vary. Both insurer and doctor calls allow up to 30 seconds of ringing and 10 seconds to press 1, with private voicemail screening. A carrier may forward to voicemail earlier; ATP ends that attempt rather than starting the conversation with the recording.

## Automated rehearsal

`PYTHONPATH=. .venv/bin/python scripts/smoke_pitch.py`

Uses real LiveKit rooms, ElevenLabs speech generation/recognition, OpenAI decisions and approval review. RTC actors replace the two telephone legs; Slack delivery is captured locally. It places no phone calls and posts no Slack messages. It verifies both private press-1 screens, treatment-history answering, a factual response to the first objection, escalation from frustration without an explicit doctor command, doctor attestation, # handback, automatic ending, and evidence-backed approval details. Time the actual phones separately before pitching.
