import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Room, RoomEvent, Track, createLocalAudioTrack } from "livekit-client";
import { QRCodeSVG } from "qrcode.react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Clock,
  Download,
  Expand,
  FileText,
  Headphones,
  HeartPulse,
  LogOut,
  Mic,
  Phone,
  PhoneOff,
  Play,
  Plus,
  Radio,
  RefreshCw,
  ShieldCheck,
  Square,
  Stethoscope,
  Users,
  Volume2,
  VolumeX,
  X,
  AlertCircle,
  ExternalLink,
  KeyRound,
} from "lucide-react";
import type { Call, Case, Checks, Role, Session, Contacts } from "./types";
import { api, post, sessionToken } from "./api";
import "./style.css";

const roleName: Record<string, string> = {
  ai: "ATP Assistant",
  payer: "Insurer representative",
  administrator: "Administrator",
  doctor: "Doctor",
  operator: "Operator",
  presentation: "Presentation",
  handoff_pending: "Human requested",
  resuming: "Returning to AI",
  paused: "Paused",
};
const isActive = (c: Call | null) =>
  !!c && !["ended", "failed"].includes(c.status);
function Brand({ light = false }: { light?: boolean }) {
  return (
    <div className={`brand ${light ? "light" : ""}`}>
      <span className="brand-icon">
        <Activity size={23} />
      </span>
      <span>
        atp<span className="brand-period">.</span>
      </span>
      <span className="brand-caption">
        ACCESS TO
        <br />
        PRESCRIPTION
      </span>
    </div>
  );
}
function Time({ call }: { call: Call | null }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const sec = call
    ? Math.max(
        0,
        Math.floor(
          ((call.ended_at ? call.ended_at * 1000 : now) -
            (call.answered_at || call.created_at) * 1000) /
            1000,
        ),
      )
    : 0;
  return (
    <span className="timer">
      {String(Math.floor(sec / 60)).padStart(2, "0")}:
      {String(sec % 60).padStart(2, "0")}
    </span>
  );
}
function callStep(call: Call | null) {
  if (!call) return 0;
  if (call.mode === "phone") {
    if (call.control === "doctor") return 1;
    return call.events.some((e) => e.text === "Doctor: handback") ? 2 : 0;
  }
  if (call.control === "doctor") return 3;
  if (call.control === "administrator") return 1;
  if (call.events.some((e) => e.text === "Doctor: handback")) return 4;
  if (call.events.some((e) => e.text === "Administrator: handback")) return 2;
  return 0;
}
function Status({ call }: { call: Call | null }) {
  return (
    <span className={`status ${isActive(call) ? "live" : ""}`}>
      <i />
      {!call
        ? "Ready to begin"
        : call.status === "active"
          ? call.control === "ai"
            ? "AI is handling the call"
            : roleName[call.control] || call.control
          : call.status.replace("_", " ")}
    </span>
  );
}

function PitchStages({ call }: { call: Call | null }) {
  if (call?.scenario !== "pitch") return null;
  const posted = call.approval_notification_status === "posted";
  const humanSpoke = call.transcript.some((t) => t.speaker === "doctor");
  const resumed = call.events.some(
    (e) =>
      e.text === "Doctor: handback" ||
      (humanSpoke && e.text === "Operator: handback"),
  );
  const stage = posted
    ? 4
    : call.control === "doctor"
      ? 2
      : call.control === "handoff_pending"
        ? 1
        : resumed
          ? 3
          : humanSpoke
            ? 2
            : 0;
  return (
    <div
      className="pitch-stages"
      aria-label="Live demo progress"
      aria-live="polite"
    >
      {["AI call", "Escalation", "Doctor", "AI resumes", "Slack approval"].map(
        (name, i) => (
          <span
            key={name}
            className={i === stage ? "current" : i < stage ? "done" : ""}
          >
            {i < stage || (i === 4 && posted) ? "✓ " : `${i + 1}. `}
            {name}
          </span>
        ),
      )}
    </div>
  );
}

function ApprovalUpdate({ call }: { call: Call | null }) {
  const update = call?.docupdates;
  if (!update) return null;
  const titles: Record<string, string> = {
    checking: "Checking the final authorization outcome…",
    ready: "Your DocUpdate has been updated · authorization approved",
    not_approved: "No confirmed approval · no approval message sent",
    review_failed: "Approval update could not be verified",
    no_public_url: "Approval confirmed · update link unavailable",
  };
  const sms: Record<string, string> = {
    pending: "Preparing DocUpdate notification",
    sending: "Posting DocUpdate notification to Slack…",
    posted: "DocUpdate notification posted to Slack",
    accepted: "Accepted by provider · delivery pending",
    delivered: "Approval text delivered to the doctor",
    unconfirmed: "Approval notification not confirmed",
    failed: "Approval notification failed",
    undelivered: "Approval text not delivered",
    rejected: "Approval text rejected",
    not_sent: "No approval notification sent",
    rehearsal: "Browser rehearsal · link created, no notification posted",
  };
  return (
    <section
      className="doctor-call-status"
      aria-label="DocUpdate notification"
      aria-live="polite"
    >
      <div>
        <FileText size={17} />
        <strong>{titles[update.state] || update.state}</strong>
      </div>
      <p>
        {sms[update.notification_status || update.sms_status || ""] ||
          update.notification_status ||
          update.sms_status}
      </p>
      {update.error && <p className="sms-error">{update.error}</p>}
      {update.url && (
        <a href={update.url} target="_blank" rel="noreferrer">
          View in DocUpdate <ArrowUpRight size={12} />
        </a>
      )}
    </section>
  );
}

function Login({ onLogin }: { onLogin: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      sessionStorage.removeItem("atp-access");
      await post("/login", { password });
      onLogin();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <section className="login-story">
        <Brand light />
        <div className="login-message">
          <span className="eyebrow">CARE DOESN’T END AT THE PRESCRIPTION</span>
          <h1>
            Less time on hold.
            <br />
            <em>More time for care.</em>
          </h1>
          <p>AI handles the routine. Your team steps in when it matters.</p>
          <div className="connection-art">
            <span>
              <Radio />
              ATP
            </span>
            <i />
            <span>
              <Users />
              Your team
            </span>
            <i />
            <span>
              <HeartPulse />
              Patient access
            </span>
          </div>
        </div>
        <div className="login-foot">Built around the human moments.</div>
      </section>
      <section className="login-form">
        <span className="eyebrow">PRACTICE WORKSPACE</span>
        <h2>Welcome to ATP.</h2>
        <p>One conversation. Your team, together.</p>
        <form onSubmit={submit}>
          <label htmlFor="password">Workspace password</label>
          <div className="input-icon">
            <KeyRound size={18} />
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your demo password"
              required
              autoFocus
            />
          </div>
          {error && (
            <div className="error">
              <AlertCircle size={17} />
              {error}
            </div>
          )}
          <button className="primary wide" disabled={busy}>
            {busy ? "Signing in…" : "Open workspace"}
            <ArrowRight size={18} />
          </button>
        </form>
        <div className="synthetic-note">
          <ShieldCheck size={17} />
          Hackathon workspace · Synthetic patient data only
        </div>
      </section>
    </div>
  );
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [contacts, setContacts] = useState<Contacts | null>(null);
  const [contactSaved, setContactSaved] = useState(false);
  const [caseData, setCase] = useState<Case | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [partial, setPartial] = useState<
    Record<string, { speaker: string; text: string }>
  >({});
  const [checks, setChecks] = useState<Checks>({});
  const [checking, setChecking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [links, setLinks] = useState<Record<string, string>>({});
  const [showLinks, setShowLinks] = useState(false);
  const [editing, setEditing] = useState(false);
  const [view, setView] = useState("workspace");
  const [pitchDemo, setPitchDemo] = useState(true);
  const [showHistory, setShowHistory] = useState(false);
  const [archiveCall, setArchiveCall] = useState<Call | null>(null);
  const [connected, setConnected] = useState(false);
  const [mic, setMic] = useState(false);
  const [muted, setMuted] = useState(false);
  const [eventOnline, setEventOnline] = useState(false);
  const [audioBusy, setAudioBusy] = useState(false);

  const [history, setHistory] = useState<
    { id: string; status: string; created_at: number }[]
  >([]);
  const roomRef = useRef<Room | null>(null);
  const audioRef = useRef<HTMLDivElement>(null);

  async function load() {
    setError("");
    try {
      if (location.pathname === "/join" && location.hash) {
        const raw = location.hash.slice(1);
        historyReplace();
        const granted = await post<{ token: string }>("/access", {
          token: raw,
        });
        sessionStorage.setItem("atp-access", granted.token);
      }
      const s = await api<Session>("/session");
      setSession(s);
      if (s.role === "operator") {
        const [c, list, destinations] = await Promise.all([
          api<Case>("/case"),
          api<{
            current: Call | null;
            history: { id: string; status: string; created_at: number }[];
          }>("/calls"),
          api<Contacts>("/contacts"),
        ]);
        setCase(c);
        setContacts(destinations);
        setCall(list.current);
        setHistory(list.history);
      } else if (s.call_id) {
        const c = await api<Call>("/calls/" + s.call_id);
        setCall(c);
        setCase(c.case);
      }
    } catch (e) {
      if (location.pathname === "/join") setError((e as Error).message);
      setSession(null);
    } finally {
      setLoaded(true);
    }
  }
  function historyReplace() {
    window.history.replaceState(null, "", location.pathname);
  }
  useEffect(() => {
    void load();
    return () => {
      void roomRef.current?.disconnect();
    };
  }, []);
  useEffect(() => {
    if (!call || !session || !isActive(call)) return;
    let stopped = false;
    let ws: WebSocket | undefined;
    let retry: number;
    function connect() {
      const token = sessionToken();
      ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/calls/${call!.id}/events`,
      );
      ws.onopen = () => {
        ws?.send(JSON.stringify({ token }));
        setPartial({});
      };
      ws.onmessage = (e) => {
        const event = JSON.parse(e.data);
        if (event.type === "snapshot") {
          setEventOnline(true);
          setCall(event.call);
        }
        if (event.type === "partial")
          setPartial((p) => ({
            ...p,
            [event.identity]: { speaker: event.speaker, text: event.text },
          }));
      };
      ws.onclose = () => {
        setEventOnline(false);
        if (!stopped) retry = window.setTimeout(connect, 1800);
      };
    }
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [
    call?.id,
    session?.role,
    call?.status === "ended" || call?.status === "failed",
  ]);
  useEffect(() => {
    const room = roomRef.current;
    if (!room || !call || !session) return;
    const own =
      call.controller_identity === session.identity &&
      call.control === session.role;
    const shouldMic = session.role === "payer" || own;
    if (!shouldMic && mic) {
      void room.localParticipant.setMicrophoneEnabled(false);
      setMic(false);
    }
    if (["ended", "failed"].includes(call.status)) {
      void room.disconnect();
      setConnected(false);
      setMic(false);
    }
  }, [call?.control, call?.status, call?.controller_identity]);
  async function check() {
    setChecking(true);
    setError("");
    try {
      setChecks(await api<Checks>("/readiness"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  }
  async function start(mode: "phone" | "browser") {
    setBusy(true);
    setError("");
    try {
      if (mode === "phone" && contacts) {
        setContacts(
          await api<Contacts>("/contacts", {
            method: "PUT",
            body: JSON.stringify(contacts),
          }),
        );
        setContactSaved(true);
      }
      await roomRef.current?.disconnect();
      roomRef.current = null;
      setConnected(false);
      setPartial({});
      setLinks({});
      const started = await post<Call>("/calls", {
        mode,
        scenario: pitchDemo ? "pitch" : "standard",
      });
      setCall(started);
      setCase(started.case);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function joinAudio() {
    if (!call) return;
    setAudioBusy(true);
    setError("");
    try {
      if (session?.role !== "presentation" && session?.role !== "operator") {
        const track = await createLocalAudioTrack({
          echoCancellation: true,
          noiseSuppression: true,
        });
        track.stop();
      }
      await roomRef.current?.disconnect();
      const r = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = r;
      r.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          el.dataset.audio = "true";
          audioRef.current?.appendChild(el);
        }
      });
      r.on(RoomEvent.TrackUnsubscribed, (track) =>
        track.detach().forEach((e) => e.remove()),
      );
      r.on(RoomEvent.Disconnected, () => {
        setConnected(false);
        setMic(false);
      });
      r.on(RoomEvent.Reconnecting, () =>
        setError("Audio connection interrupted. Reconnecting…"),
      );
      const creds = await post<{ url: string; token: string }>(
        "/calls/" + call.id + "/join",
      );
      await r.connect(creds.url, creds.token);
      await r.startAudio();
      if (session?.role === "payer") {
        await r.localParticipant.setMicrophoneEnabled(true);
        setMic(true);
      }
      setConnected(true);
      setMuted(false);
    } catch (e) {
      setError("Audio: " + (e as Error).message);
      await roomRef.current?.disconnect();
      roomRef.current = null;
      setConnected(false);
    } finally {
      setAudioBusy(false);
    }
  }
  async function command(action: string, digits = "") {
    if (!call) return;
    setBusy(true);
    setError("");
    try {
      if (action === "handback") {
        await roomRef.current?.localParticipant.setMicrophoneEnabled(false);
        setMic(false);
      }
      const updated = await post<Call>("/calls/" + call.id + "/control", {
        action,
        digits,
        revision: call.revision,
        request_id: crypto.randomUUID(),
      });
      setCall(updated);
      if (action === "takeover") {
        let last: unknown;
        for (let i = 0; i < 5; i++) {
          try {
            await roomRef.current!.localParticipant.setMicrophoneEnabled(true);
            last = null;
            break;
          } catch (e) {
            last = e;
            await new Promise((r) => setTimeout(r, 200));
          }
        }
        if (last)
          throw new Error(
            "Control transferred, but microphone could not start. Return to AI and reconnect audio.",
          );
        setMic(true);
      }
    } catch (e) {
      setError((e as Error).message);
      try {
        setCall(await api<Call>("/calls/" + call.id));
      } catch {}
    } finally {
      setBusy(false);
    }
  }
  async function getLinks() {
    if (!call) return;
    try {
      setLinks(
        await post<Record<string, string>>("/calls/" + call.id + "/join-links"),
      );
      setShowLinks(true);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function leave() {
    if (call?.controller_identity === session?.identity) {
      setError("Return control to AI before leaving.");
      return;
    }
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setConnected(false);
    setMic(false);
  }
  function toggleSound() {
    setMuted(!muted);
    audioRef.current
      ?.querySelectorAll("audio")
      .forEach((a) => (a.muted = !muted));
  }
  const presentation =
    session?.role === "presentation" || view === "presentation";
  if (!loaded)
    return (
      <div className="loading">
        <Brand />
        <span>Opening your workspace…</span>
      </div>
    );
  if (!session)
    return (
      <>
        {error && (
          <div className="join-error">
            {error} <a href="/">Open workspace</a>
          </div>
        )}
        <Login onLogin={load} />
      </>
    );
  const phoneControl = !!session.phone_control;
  const briefing =
    call?.briefing || (phoneControl ? call?.doctor_call?.briefing : null);
  const mobile =
    session.role === "administrator" ||
    session.role === "doctor" ||
    session.role === "payer";
  return (
    <div
      className={
        presentation ? "presentation" : mobile ? "mobile-app" : "app-shell"
      }
    >
      <div ref={audioRef} className="audio-elements" />
      {!mobile && !presentation && (
        <aside className="sidebar">
          <Brand />
          <div className="workspace-label">NORTHLINE CARDIOLOGY</div>
          <nav>
            <button className="selected" onClick={() => setView("workspace")}>
              <ClipboardList size={19} />
              Workspace<span>01</span>
            </button>
            <button
              onClick={() => {
                setView("workspace");
                document
                  .getElementById("conversation")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
            >
              <Activity size={19} />
              Conversation
            </button>
            <button
              onClick={async () => {
                try {
                  const list = await api<{ history: typeof history }>("/calls");
                  setHistory(list.history);
                  setArchiveCall(null);
                  setShowHistory(true);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              <Clock size={19} />
              Call history
            </button>
            <button onClick={() => setEditing(true)}>
              <FileText size={19} />
              Case records
            </button>
          </nav>
          <div className="sidebar-bottom">
            <div className="demo-label">
              <span />
              DEMO WORKSPACE
            </div>
            <p>
              A little less waiting.
              <br />A little more care.
            </p>
            <button
              onClick={async () => {
                await post("/logout");
                setSession(null);
              }}
            >
              <LogOut size={16} />
              Sign out
            </button>
          </div>
        </aside>
      )}
      <div className="main">
        <header className={presentation ? "pitch-header" : "topbar"}>
          {presentation ? (
            <Brand light />
          ) : mobile ? (
            <Brand />
          ) : (
            <span className="breadcrumb">
              Workspace <ChevronRight size={14} />{" "}
              <strong>Prescription access</strong>
            </span>
          )}
          <div className="topbar-right">
            {presentation ? (
              <>
                <span className="eyebrow">
                  LIVE CONVERSATION · PRIOR AUTHORIZATION
                </span>
                <Status call={call} />
                <Time call={call} />
                {session.role === "operator" && (
                  <button
                    className="icon-button"
                    title="Exit presentation"
                    onClick={() => setView("workspace")}
                  >
                    <X />
                  </button>
                )}
              </>
            ) : (
              <>
                <span className="synthetic-pill">SYNTHETIC DEMO</span>
                <span className="avatar">
                  {mobile ? (session.role === "doctor" ? "DR" : "AD") : "NC"}
                </span>
              </>
            )}
          </div>
        </header>
        {error && (
          <div role="alert" className="error page-error">
            <AlertCircle size={18} />
            <span>{error}</span>
            <button className="icon-button" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {mobile ? (
          <>
            <section className="mobile-heading">
              <span className="eyebrow">
                {session.role === "payer"
                  ? "INSURER SIMULATION"
                  : `${session.role.toUpperCase()} · LIVE ASSIST`}
              </span>
              <h1>
                {session.role === "payer"
                  ? "You’re the representative."
                  : "Your expertise.\nRight when it matters."}
              </h1>
              <p>
                {caseData?.patient} · {caseData?.medication}
              </p>
            </section>
            {call && (
              <>
                <section className="mobile-status">
                  <Status call={call} />
                  <Time call={call} />
                </section>
                <section className="briefing">
                  <span className="eyebrow">
                    {briefing ? "YOUR BRIEFING" : "CASE AT A GLANCE"}
                  </span>
                  <h3>{briefing?.reason || caseData?.request}</h3>
                  <p>
                    {phoneControl
                      ? "Answer ATP's incoming phone call and press 1 to join the insurer. Press # on that call, or use the button below, when you want the AI to continue."
                      : briefing
                        ? "The AI is waiting for your help. Your microphone stays off until you take over."
                        : caseData?.evidence}
                  </p>
                </section>
                <div className="mobile-controls">
                  {phoneControl ? (
                    <>
                      <div className="connection-state">
                        <Phone size={17} />
                        {call.doctor_call?.status === "connected"
                          ? "Your phone is connected to the insurer"
                          : call.doctor_call?.status === "screening"
                            ? "Press 1 on your phone keypad to join"
                            : call.doctor_call?.status === "returned"
                              ? "ATP is continuing the insurer call"
                              : call.doctor_call?.status === "failed"
                                ? "Phone call did not connect"
                                : "ATP is calling your phone"}
                      </div>
                      <button
                        className="primary wide"
                        disabled={
                          busy ||
                          call.controller_identity !== session.identity ||
                          !isActive(call)
                        }
                        onClick={() => command("handback")}
                      >
                        <Radio size={19} />
                        Return to AI
                      </button>
                      <p className="help">
                        Your audio uses the phone call. No browser microphone is
                        needed. Returning to AI ends your connection while the
                        insurer stays on the line.
                      </p>
                    </>
                  ) : !connected ? (
                    <button
                      className="primary wide"
                      onClick={joinAudio}
                      disabled={audioBusy || !isActive(call)}
                    >
                      <Headphones size={19} />
                      {audioBusy ? "Connecting…" : "Enable audio & join"}
                    </button>
                  ) : (
                    <>
                      <div className="connection-state">
                        <span className="dot" />
                        {mic
                          ? "Your microphone is live"
                          : "Connected · listening only"}
                      </div>
                      {session.role !== "payer" &&
                        (call.controller_identity === session.identity ? (
                          <button
                            className="primary wide"
                            onClick={() => command("handback")}
                            disabled={busy}
                          >
                            <Radio size={19} />
                            Return to AI
                          </button>
                        ) : (
                          <button
                            className="primary wide"
                            onClick={() => command("takeover")}
                            disabled={
                              busy ||
                              ["administrator", "doctor"].includes(call.control)
                            }
                          >
                            <Mic size={19} />
                            Take over
                          </button>
                        ))}
                      <button
                        className="secondary wide"
                        onClick={leave}
                        disabled={call.controller_identity === session.identity}
                      >
                        Leave audio
                      </button>
                    </>
                  )}
                  <p className="help">
                    {phoneControl
                      ? "You can also press # using your phone’s call keypad."
                      : "Keep Safari open and your phone unlocked. Use headphones during the pitch."}
                  </p>
                </div>
                <Transcript call={call} partial={partial} compact />
              </>
            )}
          </>
        ) : presentation ? (
          <div className="pitch-body">
            <section className="pitch-transcript">
              <PitchStages call={call} />
              <div className="section-label">
                <span className="eyebrow">THE CONVERSATION</span>
                <span>
                  {!call
                    ? "READY"
                    : !isActive(call)
                      ? "CALL ENDED"
                      : eventOnline
                        ? "CONNECTED"
                        : "RECONNECTING"}
                </span>
              </div>
              <Transcript call={call} partial={partial} />
              <div className="pitch-audio">
                <button
                  className="pitch-button"
                  disabled={!isActive(call) || audioBusy}
                  onClick={connected ? toggleSound : joinAudio}
                >
                  {connected ? (
                    muted ? (
                      <VolumeX size={17} />
                    ) : (
                      <Volume2 size={17} />
                    )
                  ) : (
                    <Headphones size={17} />
                  )}{" "}
                  {connected
                    ? muted
                      ? "Enable sound"
                      : "Mute sound"
                    : "Listen to call"}
                </button>
                <span>
                  {call?.mode === "browser"
                    ? "BROWSER REHEARSAL"
                    : "LIVE TELEPHONE DEMO"}
                </span>
              </div>
            </section>
            <Facts call={call} pitch />
          </div>
        ) : (
          <>
            <section className="page-heading">
              <div>
                <span className="eyebrow">PRESCRIPTION ACCESS</span>
                <h1>Move care forward.</h1>
                <p>
                  Routine conversations, handled. Human expertise, always within
                  reach.
                </p>
              </div>
              <button
                className="secondary"
                onClick={() => setView("presentation")}
              >
                <Expand size={17} />
                Presentation view
                <ArrowUpRight size={16} />
              </button>
            </section>
            <div className="workspace-grid">
              <div className="workspace-primary">
                <section className="case-card">
                  <div className="card-top">
                    <span className="eyebrow">ACTIVE CASE · ATP-001</span>
                    <button
                      className="text-button"
                      onClick={() => setEditing(true)}
                      disabled={isActive(call)}
                    >
                      View records
                      <ArrowUpRight size={15} />
                    </button>
                  </div>
                  <div className="patient-row">
                    <div className="patient-avatar">ME</div>
                    <div>
                      <h2>{caseData?.patient}</h2>
                      <p>{caseData?.diagnosis}</p>
                    </div>
                    <span className="case-tag">Prior authorization</span>
                  </div>
                  <div className="case-details">
                    <div>
                      <span>MEDICATION</span>
                      <strong>{caseData?.medication}</strong>
                      <small>{caseData?.dose}</small>
                    </div>
                    <div>
                      <span>PRESCRIBER</span>
                      <strong>{caseData?.provider}</strong>
                      <small>{caseData?.practice}</small>
                    </div>
                    <div>
                      <span>PAYER</span>
                      <strong>{caseData?.payer.split(" · ")[0]}</strong>
                      <small>Consenting demo representative</small>
                    </div>
                  </div>
                  <div className="case-request">
                    <FileText size={17} />
                    <span>{caseData?.request}</span>
                  </div>
                </section>
                {contacts && (
                  <section className="destinations-card">
                    <div className="card-top">
                      <div>
                        <span className="eyebrow">CALL DESTINATIONS</span>
                        <h2>Two numbers. One conversation.</h2>
                      </div>
                      <Phone size={20} />
                    </div>
                    <p>
                      ATP calls the insurer and handles the conversation. When
                      it needs you, it calls the doctor and posts a briefing in
                      Slack.
                    </p>
                    <form
                      onSubmit={async (e) => {
                        e.preventDefault();
                        setBusy(true);
                        setError("");
                        try {
                          setContacts(
                            await api<Contacts>("/contacts", {
                              method: "PUT",
                              body: JSON.stringify(contacts),
                            }),
                          );
                          setContactSaved(true);
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <div className="destination-fields">
                        <label>
                          Insurer phone number
                          <input
                            type="tel"
                            value={contacts.insurer_phone_number}
                            placeholder="+1…"
                            required
                            disabled={isActive(call)}
                            onChange={(e) => {
                              setContactSaved(false);
                              setContacts({
                                ...contacts,
                                insurer_phone_number: e.target.value,
                              });
                            }}
                          />
                          <small>The main call ATP handles for you</small>
                        </label>
                        <label>
                          Doctor phone number
                          <input
                            type="tel"
                            value={contacts.doctor_phone_number}
                            placeholder="+1…"
                            required
                            disabled={isActive(call)}
                            onChange={(e) => {
                              setContactSaved(false);
                              setContacts({
                                ...contacts,
                                doctor_phone_number: e.target.value,
                              });
                            }}
                          />
                          <small>
                            Receives the help call; briefings appear in Slack
                          </small>
                        </label>
                      </div>
                      <button
                        className="secondary"
                        disabled={busy || isActive(call)}
                      >
                        {contactSaved ? <Check size={15} /> : null}
                        {contactSaved ? "Numbers saved" : "Save numbers"}
                      </button>
                      <span className="destination-note">
                        Include the country code. Changes apply to the next
                        call.
                      </span>
                    </form>
                  </section>
                )}
                <section className="call-card">
                  <div className="card-top">
                    <div>
                      <span className="eyebrow">CONVERSATION CONTROL</span>
                      <h2>
                        {isActive(call)
                          ? "Your team is on the line."
                          : "Ready when you are."}
                      </h2>
                    </div>
                    <div
                      className={`signal-orb ${isActive(call) ? "active" : ""}`}
                    >
                      <Radio size={24} />
                    </div>
                  </div>
                  {!isActive(call) && (
                    <div className="pitch-setup">
                      <label>
                        <input
                          type="checkbox"
                          checked={pitchDemo}
                          onChange={(e) => setPitchDemo(e.target.checked)}
                        />{" "}
                        Pitch demo · 90-second target
                      </label>
                      <p>
                        {pitchDemo
                          ? "Uses fictional Morgan Ellis / Repatha. Case review → lab evidence → clinical objection → doctor → Slack approval."
                          : "Uses your saved source case and standard call behavior."}
                      </p>
                      {pitchDemo && (
                        <details>
                          <summary>Show rehearsal cues</summary>
                          <p>
                            <strong>Fictional chart:</strong> Morgan has
                            familial hypercholesterolemia. LDL fell from 260 to
                            190 mg/dL after atorvastatin (started May 1) and
                            ezetimibe (added June 1). The doctor must confirm
                            adherence and maximally tolerated therapy.
                          </p>
                          <p>
                            <strong>Insurer:</strong> Answer and press 1 to
                            connect. Then: “I have the case. What treatment
                            history was submitted?”
                          </p>
                          <p>
                            <strong>First pushback:</strong> “Those trials alone
                            aren’t enough. What do the labs show?” Let ATP
                            explain the LDL trend and ask what is still needed.
                          </p>
                          <p>
                            <strong>Then, frustrated:</strong> “We keep going in
                            circles. I can’t approve this without someone taking
                            clinical responsibility.” ATP should bring in the
                            doctor without you explicitly requesting a transfer.
                          </p>
                          <p>
                            <strong>Doctor:</strong> Answer, press 1: “Dr. Chen
                            here. I verified adherence. These are Morgan’s
                            maximally tolerated therapies, and LDL remains 190.
                            I recommend proceeding with Repatha.” Pause a
                            second, then press #.
                          </p>
                          <p>
                            <strong>Insurer:</strong> After ATP resumes: “Morgan
                            Ellis’s Repatha authorization is approved for twelve
                            months. Reference D E M O, eight four nine two one.
                            The pharmacy can process it. That completes the
                            case. Goodbye.”
                          </p>
                          <p>
                            Wait for ATP to end the call. Open the authorization
                            update in Slack. Timing is a target, not a forced
                            cutoff.
                          </p>
                        </details>
                      )}
                    </div>
                  )}
                  <PitchStages call={call} />
                  <div className="call-progress">
                    {(call?.mode === "browser"
                      ? [
                          "ATP Assistant",
                          "Administrator",
                          "ATP Assistant",
                          "Doctor",
                          "ATP Assistant",
                        ]
                      : ["ATP Assistant", "Doctor", "ATP Assistant"]
                    ).map((name, i) => (
                      <React.Fragment key={i}>
                        {i > 0 && <span className="progress-line" />}
                        <div
                          className={
                            isActive(call) && i === callStep(call)
                              ? "progress-person current"
                              : i < callStep(call)
                                ? "progress-person done"
                                : "progress-person"
                          }
                        >
                          <span>
                            {name === "ATP Assistant" ? (
                              <Activity size={17} />
                            ) : name === "Doctor" ? (
                              <Stethoscope size={17} />
                            ) : (
                              <Users size={17} />
                            )}
                          </span>
                          <small>
                            {name === "ATP Assistant" ? "AI" : name}
                          </small>
                        </div>
                      </React.Fragment>
                    ))}
                  </div>
                  {call?.briefing && (
                    <div className="handoff-alert">
                      <Users size={20} />
                      <div>
                        <strong>
                          {roleName[call.briefing.role]} requested
                        </strong>
                        <p>{call.briefing.reason}</p>
                      </div>
                      <button
                        className="text-button"
                        disabled={busy}
                        onClick={() => command("unavailable")}
                      >
                        Human unavailable
                      </button>
                      <button className="text-button" onClick={getLinks}>
                        Invite
                        <ArrowRight size={16} />
                      </button>
                    </div>
                  )}
                  {call?.doctor_call && isActive(call) && (
                    <div className="doctor-call-status">
                      <div>
                        <Phone size={17} />
                        <strong>
                          {(
                            {
                              ended: "Doctor call ended",
                              calling: "Calling your doctor…",
                              screening:
                                "Doctor answered · waiting for press 1",
                              connected: "Doctor is on the insurer call",
                              returned: "Doctor handed back to AI",
                              failed: "Doctor call did not connect",
                              cancelled: "Doctor call cancelled",
                            } as Record<string, string>
                          )[call.doctor_call.status] || call.doctor_call.status}
                        </strong>
                      </div>
                      <p>
                        Slack briefing:{" "}
                        {(
                          {
                            pending: "Preparing",
                            posted: "Posted to Slack",
                            unavailable: "Not configured",
                            accepted: "Accepted by provider · delivery pending",
                            delivered: "Delivered",
                            unconfirmed: "Delivery not confirmed",
                            failed: "Failed",
                            undelivered: "Not delivered",
                            rejected: "Rejected",
                          } as Record<string, string>
                        )[
                          call.doctor_call.notification_status ||
                            call.doctor_call.sms_status ||
                            "pending"
                        ] ||
                          call.doctor_call.notification_status ||
                          call.doctor_call.sms_status}
                      </p>
                      {(call.doctor_call.notification_error ||
                        call.doctor_call.sms_error) && (
                        <p className="sms-error">
                          {call.doctor_call.notification_error ||
                            call.doctor_call.sms_error}
                        </p>
                      )}
                      {call.doctor_call.error && (
                        <p className="sms-error">{call.doctor_call.error}</p>
                      )}
                      {call.doctor_call.status === "failed" &&
                        ["ai", "handoff_pending"].includes(call.control) && (
                          <button
                            className="secondary"
                            onClick={async () => {
                              try {
                                setCall(
                                  await post<Call>(
                                    "/calls/" + call.id + "/call-doctor",
                                  ),
                                );
                              } catch (e) {
                                setError((e as Error).message);
                              }
                            }}
                          >
                            Retry doctor call
                          </button>
                        )}
                      {call.doctor_call.control_url && isActive(call) && (
                        <a
                          href={call.doctor_call.control_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open doctor briefing & controls{" "}
                          <ArrowUpRight size={12} />
                        </a>
                      )}
                    </div>
                  )}
                  <ApprovalUpdate call={call} />
                  {call?.error && (
                    <div className="error">
                      <AlertCircle size={18} />
                      {call.error}
                    </div>
                  )}
                  <div className="call-actions">
                    {!isActive(call) ? (
                      <>
                        <button
                          className="primary"
                          onClick={() => start("phone")}
                          disabled={busy}
                        >
                          <Phone size={17} />
                          {busy ? "Starting…" : "Start insurer call"}
                        </button>
                        <button
                          className="secondary"
                          onClick={() => start("browser")}
                          disabled={busy}
                        >
                          <Play size={16} />
                          Browser rehearsal
                        </button>
                      </>
                    ) : (
                      <>
                        <button className="primary" onClick={getLinks}>
                          <Plus size={17} />
                          {call?.mode === "phone"
                            ? "Browser links"
                            : "Invite your team"}
                        </button>
                        <button
                          className="secondary"
                          onClick={connected ? toggleSound : joinAudio}
                          disabled={audioBusy}
                        >
                          {connected ? (
                            muted ? (
                              <VolumeX size={17} />
                            ) : (
                              <Volume2 size={17} />
                            )
                          ) : (
                            <Headphones size={17} />
                          )}{" "}
                          {connected
                            ? muted
                              ? "Sound off"
                              : "Listening"
                            : "Listen"}
                        </button>
                        <button
                          className="danger icon-button"
                          title="End insurer call"
                          onClick={() => command("end")}
                          disabled={busy}
                        >
                          <PhoneOff size={18} />
                        </button>
                      </>
                    )}
                  </div>
                  <div className="call-footer">
                    <Status call={call} />
                    <Time call={call} />
                  </div>
                  {isActive(call) && (
                    <div className="operator-controls">
                      <button
                        className="text-button"
                        onClick={() =>
                          command(
                            call?.control === "paused" ||
                              call?.control === "handoff_pending"
                              ? "handback"
                              : "pause",
                          )
                        }
                        disabled={busy}
                      >
                        {call?.control === "paused" ||
                        call?.control === "handoff_pending" ? (
                          <Play size={14} />
                        ) : (
                          <Square size={13} />
                        )}{" "}
                        {call?.control === "paused" ||
                        call?.control === "handoff_pending"
                          ? "Resume AI"
                          : "Pause AI"}
                      </button>
                      <Keypad
                        onDigits={(d) => command("dtmf", d)}
                        disabled={busy}
                      />
                    </div>
                  )}
                </section>
                <section id="conversation" className="conversation-card">
                  <div className="card-top">
                    <div>
                      <span className="eyebrow">LIVE TRANSCRIPT</span>
                      <h2>The conversation, in context.</h2>
                    </div>
                    {call && (
                      <button
                        className="icon-button"
                        title="Export transcript"
                        onClick={() =>
                          window.open(`/api/calls/${call.id}/export`, "_blank")
                        }
                      >
                        <Download size={18} />
                      </button>
                    )}
                  </div>
                  <Transcript call={call} partial={partial} />
                </section>
              </div>
              <aside className="workspace-secondary">
                <Facts call={call} />
                <section className="readiness-card">
                  <div className="card-top">
                    <h3>Connection check</h3>
                    <button
                      className={`icon-button ${checking ? "spin" : ""}`}
                      title="Check services"
                      onClick={check}
                      disabled={checking}
                    >
                      <RefreshCw size={16} />
                    </button>
                  </div>
                  {Object.keys(checks).length ? (
                    Object.entries(checks).map(([name, c]) => (
                      <div className="service" key={name} title={c.detail}>
                        <span>{name}</span>
                        <span className={c.ok ? "service-ok" : "service-error"}>
                          {c.ok ? (
                            <CheckCircle2 size={14} />
                          ) : (
                            <AlertCircle size={14} />
                          )}{" "}
                          {c.ok ? "Ready" : "Check setup"}
                        </span>
                      </div>
                    ))
                  ) : (
                    <>
                      <p>
                        Verify voice, audio, and telephone access before your
                        first call.
                      </p>
                      <button
                        className="text-button"
                        onClick={check}
                        disabled={checking}
                      >
                        {checking
                          ? "Checking connections…"
                          : "Check all services"}
                        <ArrowRight size={15} />
                      </button>
                    </>
                  )}
                  <div className="small-note">
                    <ShieldCheck size={14} />
                    Keys stay on your laptop.
                  </div>
                </section>
                <div className="care-note">
                  <HeartPulse size={20} />
                  <p>
                    AI handles the routine.
                    <br />
                    <strong>People handle the moments.</strong>
                  </p>
                </div>
              </aside>
            </div>
          </>
        )}
      </div>
      {showLinks && (
        <div className="modal-overlay" onClick={() => setShowLinks(false)}>
          <section
            className="modal join-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="card-top">
              <div>
                <span className="eyebrow">BRING YOUR TEAM IN</span>
                <h2>Same call. The right person.</h2>
              </div>
              <button
                className="icon-button"
                onClick={() => setShowLinks(false)}
              >
                <X />
              </button>
            </div>
            <p>
              Scan on each phone. Links are private, single-use, and expire
              after two hours.
            </p>
            <div className="join-grid">
              {Object.entries(links).map(([role, url]) => (
                <div className="join-card" key={role}>
                  <h3>{roleName[role]}</h3>
                  <QRCodeSVG value={url} size={132} marginSize={2} />
                  <button
                    className="text-button"
                    onClick={() => navigator.clipboard.writeText(url)}
                  >
                    Copy link
                    <ArrowUpRight size={14} />
                  </button>
                  <a href={url} target="_blank" rel="noreferrer">
                    Open here
                    <ExternalLink size={12} />
                  </a>
                </div>
              ))}
            </div>
            {Object.values(links).some(
              (u) => u.includes("127.0.0.1") || u.includes("localhost"),
            ) && (
              <div className="error">
                <AlertCircle size={16} />
                Run make demo for an HTTPS link accessible from phones.
              </div>
            )}
          </section>
        </div>
      )}
      {showHistory && (
        <div className="modal-overlay">
          <section className="modal">
            <div className="card-top">
              <h2>Call history</h2>
              <button
                aria-label="Close history"
                className="icon-button"
                onClick={() => setShowHistory(false)}
              >
                <X />
              </button>
            </div>
            {archiveCall ? (
              <>
                <div className="history-detail">
                  <Status call={archiveCall} />
                  <Time call={archiveCall} />
                  <button
                    className="text-button"
                    onClick={() => setArchiveCall(null)}
                  >
                    Back to calls
                  </button>
                  <a
                    href={`/api/calls/${archiveCall.id}/export`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Export JSON
                  </a>
                </div>
                <ApprovalUpdate call={archiveCall} />
                <Transcript call={archiveCall} partial={{}} />
                <Facts call={archiveCall} />
              </>
            ) : (
              <div className="history-list">
                {history.length ? (
                  history.map((item) => (
                    <button
                      key={item.id}
                      onClick={async () => {
                        try {
                          setArchiveCall(
                            await api<Call>("/history/" + item.id),
                          );
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      <span>
                        {new Date(item.created_at * 1000).toLocaleString()}
                      </span>
                      <span>{item.status}</span>
                      <ArrowRight size={15} />
                    </button>
                  ))
                ) : (
                  <p>No calls yet.</p>
                )}
              </div>
            )}
          </section>
        </div>
      )}
      {editing && caseData && (
        <CaseEditor
          data={caseData}
          readOnly={isActive(call)}
          onClose={() => setEditing(false)}
          onSave={async (data) => {
            setCase(
              await api<Case>("/case", {
                method: "PATCH",
                body: JSON.stringify(data),
              }),
            );
            setEditing(false);
          }}
        />
      )}
    </div>
  );
}

function Keypad({
  onDigits,
  disabled,
}: {
  onDigits: (d: string) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="keypad">
      <button className="text-button" onClick={() => setOpen(!open)}>
        Keypad
      </button>
      {open && (
        <div className="keypad-popover">
          {"123456789*0#".split("").map((d) => (
            <button disabled={disabled} key={d} onClick={() => onDigits(d)}>
              {d}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
function Transcript({
  call,
  partial,
  compact = false,
}: {
  call: Call | null;
  partial: Record<string, { speaker: string; text: string }>;
  compact?: boolean;
}) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const panel = bottom.current?.parentElement;
    if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: "smooth" });
  }, [call?.transcript.length, partial]);
  return (
    <div className={`transcript ${compact ? "compact" : ""}`}>
      {!call?.transcript.length &&
      !Object.values(partial).some((p) => p.text) ? (
        <div className="empty-transcript">
          <span className="empty-wave">▂ ▅ ▃ ▇ ▄ ▂ ▅</span>
          <h3>
            {isActive(call)
              ? "Listening for the conversation."
              : "A conversation that moves care forward."}
          </h3>
          <p>
            {isActive(call)
              ? "Spoken words will appear here as they happen."
              : "Start a call to follow every question, answer, and handoff in real time."}
          </p>
        </div>
      ) : (
        <>
          {call?.transcript.map((t) => (
            <article className={`turn ${t.speaker}`} key={t.id}>
              <div className="turn-label">
                <span>{roleName[t.speaker] || t.speaker}</span>
                <time>
                  {new Date(t.time * 1000).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </div>
              <p>
                {t.text}
                {t.interrupted && (
                  <small className="interrupted"> · interrupted</small>
                )}
              </p>
            </article>
          ))}
          {Object.entries(partial)
            .filter(([, p]) => p.text)
            .map(([id, p]) => (
              <article className={`turn partial ${p.speaker}`} key={id}>
                <div className="turn-label">
                  <span>{roleName[p.speaker] || p.speaker}</span>
                  <span className="typing-dots">•••</span>
                </div>
                <p>{p.text}</p>
              </article>
            ))}
        </>
      )}
      <div ref={bottom} />
    </div>
  );
}
const groups = [
  {
    title: "CALL SETUP",
    rows: [
      ["provider", "Provider"],
      ["member_id", "Member ID"],
    ],
  },
  {
    title: "PRIOR AUTHORIZATION",
    rows: [
      ["medication", "Medication"],
      ["authorization_status", "Status"],
      ["reference_number", "Reference number"],
      ["requirements", "Requirements"],
      ["approval_window", "Approval window"],
    ],
  },
  {
    title: "WHAT HAPPENS NEXT",
    rows: [
      ["pharmacy", "Pharmacy"],
      ["medication_access", "Medication access"],
      ["next_action", "Next action"],
      ["owner", "Owner"],
      ["due_date", "Due date"],
    ],
  },
];
function Facts({
  call,
  pitch = false,
}: {
  call: Call | null;
  pitch?: boolean;
}) {
  const count = Object.keys(call?.facts || {}).length;
  return (
    <section className={`facts-card ${pitch ? "pitch-facts" : ""}`}>
      <div className="card-top">
        <span className="eyebrow">CASE PROGRESS</span>
        <span className="facts-count">{count} captured</span>
      </div>
      <h2>Prior authorization</h2>
      <p className="facts-subtitle">
        {call?.case.medication || "Repatha"} <span>·</span>{" "}
        {call?.case.patient || "Morgan Ellis"}
      </p>
      <div className="facts-progress">
        <div style={{ width: Math.min((count / 12) * 100, 100) + "%" }} />
      </div>
      {groups.map((g) => (
        <div className="fact-group" key={g.title}>
          <h4>{g.title}</h4>
          {g.rows.map(([key, label]) => {
            const f = call?.facts[key];
            return (
              <div className={`fact-row ${f ? "captured" : ""}`} key={key}>
                <span>{label}</span>
                <div
                  title={
                    f
                      ? `${f.source === "payer" ? "Payer statement" : "Human statement"} · evidence: ${f.evidence_turn_ids.join(", ")}`
                      : ""
                  }
                >
                  {f ? (
                    <>
                      <strong>{f.value}</strong>
                      <Check size={14} />
                    </>
                  ) : (
                    <span className="dash">—</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <div className="facts-note">
        <ShieldCheck size={14} />
        <span>
          Captured from the conversation.
          <br />
          Approval and medication access are tracked separately.
        </span>
      </div>
    </section>
  );
}
function CaseEditor({
  data,
  readOnly,
  onClose,
  onSave,
}: {
  data: Case;
  readOnly: boolean;
  onClose: () => void;
  onSave: (c: Case) => Promise<void>;
}) {
  const [draft, setDraft] = useState(data);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fields = [
    ["patient", "Patient name"],
    ["date_of_birth", "Date of birth"],
    ["member_id", "Member ID"],
    ["provider", "Provider"],
    ["provider_npi", "Provider NPI"],
    ["practice", "Practice"],
    ["medication", "Medication"],
    ["dose", "Dose"],
    ["payer", "Payer"],
    ["diagnosis", "Diagnosis"],
    ["request", "Call objective"],
    ["evidence", "Source evidence"],
  ] as const;
  return (
    <div className="modal-overlay">
      <section className="modal editor">
        <div className="card-top">
          <div>
            <span className="eyebrow">SYNTHETIC CASE RECORD</span>
            <h2>Give the conversation context.</h2>
          </div>
          <button className="icon-button" onClick={onClose}>
            <X />
          </button>
        </div>
        <p>These are supplied facts, not confirmations from the payer.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await onSave(draft);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="edit-grid">
            {fields.map(([key, label]) => (
              <label
                className={
                  key === "evidence" || key === "request" ? "span-two" : ""
                }
                key={key}
              >
                {label}
                {key === "evidence" || key === "request" ? (
                  <textarea
                    value={draft[key]}
                    disabled={readOnly}
                    rows={key === "evidence" ? 5 : 2}
                    onChange={(e) =>
                      setDraft({ ...draft, [key]: e.target.value })
                    }
                  />
                ) : (
                  <input
                    value={draft[key]}
                    disabled={readOnly}
                    onChange={(e) =>
                      setDraft({ ...draft, [key]: e.target.value })
                    }
                  />
                )}
              </label>
            ))}
          </div>
          {error && <div className="error">{error}</div>}
          <div className="editor-footer">
            <span>
              {readOnly
                ? "End the call to edit its source records."
                : "Synthetic records only."}
            </span>
            <button className="primary" disabled={readOnly || busy}>
              Save case
              <Check size={16} />
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
