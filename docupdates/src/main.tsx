import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronLeft,
  Copy,
  Download,
  FileText,
  MessageSquare,
  Pill,
  X,
} from "lucide-react";
import sample from "./authorization.json";
import { parseRecord, readSource, type AuthorizationRecord } from "./record";
import "./style.css";

const samplePath = `/u/${sample.token}`;
const isSample = [
  "/",
  "/demo",
  "/demo/",
  samplePath,
  `${samplePath}/`,
].includes(location.pathname);
const updatePath = isSample ? samplePath : location.pathname + location.search;
const isDemo = location.pathname.replace(/\/$/, "") === "/demo";

function Brand() {
  return (
    <a
      className="brand"
      href={updatePath}
      aria-label="DocUpdates authorization"
    >
      <img src="/brand/impiricus.svg" alt="Impiricus" />
      <span className="brand-divider" />
      <span className="product">
        Doc<span>Updates</span>
      </span>
    </a>
  );
}

function Form({ record }: { record: AuthorizationRecord }) {
  const live = record.source === "atp";
  return (
    <article className="approval-form">
      <div className="form-top">
        <div>
          <b className="payer-brand">
            {live ? "DOCUPDATES / ATP" : "MERIDIAN BENEFITS"}
          </b>
          <p>
            {live
              ? "Completed authorization call"
              : "Pharmacy Services · Coverage Determination"}
          </p>
        </div>
        <span className="mock-stamp">
          {live ? "ATP CALL SUMMARY" : "MOCK DOCUMENT"}
        </span>
      </div>
      <div className="form-heading">
        <p className="eyebrow">
          {live ? "CALL CONFIRMATION" : "NOTICE OF DETERMINATION"}
        </p>
        <h2>{record.documentTitle || "Prior Authorization Approval"}</h2>
        <p>
          Issued {record.completedDate} at {record.completedTime}
        </p>
      </div>
      <div className="form-approved">
        <CheckCircle2 size={20} />
        <strong>APPROVED</strong>
        <span>Reference {record.authorizationId}</span>
      </div>
      <h3>Member & prescriber information</h3>
      <dl className="form-grid">
        <div>
          <dt>Patient name</dt>
          <dd>{record.patient}</dd>
        </div>
        <div>
          <dt>Date of birth</dt>
          <dd>{record.birthDate}</dd>
        </div>
        <div>
          <dt>Member ID</dt>
          <dd>{record.memberId}</dd>
        </div>
        <div>
          <dt>Prescribing clinician</dt>
          <dd>{record.provider}</dd>
        </div>
        <div>
          <dt>Practice</dt>
          <dd>{record.practice}</dd>
        </div>
        <div>
          <dt>Diagnosis</dt>
          <dd>{record.diagnosis}</dd>
        </div>
      </dl>
      <h3>Authorized medication & coverage</h3>
      <dl className="form-grid">
        <div>
          <dt>Medication</dt>
          <dd>
            {record.medication}
            {record.generic && ` (${record.generic})`}
          </dd>
        </div>
        <div>
          <dt>Insurance plan</dt>
          <dd>{record.payer}</dd>
        </div>
        <div>
          <dt>Dosing instructions</dt>
          <dd>{record.dose}</dd>
        </div>
        <div>
          <dt>Quantity limit</dt>
          <dd>{record.quantity}</dd>
        </div>
        <div>
          <dt>Coverage period</dt>
          <dd>
            {record.coveragePeriod ||
              `${record.coverageStart} – ${record.coverageEnd}`}
          </dd>
        </div>
      </dl>
      <h3>Determination & next steps</h3>
      <p>{record.summary}</p>
      <p>{record.nextStep}</p>
      <p className="form-fine">{record.documentNote}</p>
      <p className="form-fine">
        Authorization is subject to member eligibility and plan benefits at the
        time of dispensing. Approval does not confirm medication dispensing or
        the patient’s final out-of-pocket cost.
      </p>
      <footer className="form-footer">
        <strong>FICTIONAL DEMO — NOT VALID FOR CLINICAL OR BILLING USE</strong>
        <span>
          {live
            ? "Summary of a synthetic ATP call. Not a payer-issued approval letter."
            : "All patient, payer, and authorization details are simulated. · Page 1 of 1"}
        </span>
      </footer>
    </article>
  );
}

function Reader() {
  const [record, setRecord] = useState<AuthorizationRecord | null>(
    isSample ? sample : null,
  );
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (isSample) return;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let mounted = true;
    setError("");
    async function load() {
      try {
        const match = location.pathname.match(/^\/u\/([A-Za-z0-9_-]{43})\/?$/);
        if (!match)
          throw new Error(
            "This link does not match an authorization. Check the full link in your text message.",
          );
        const source = readSource(
          new URLSearchParams(location.search).get("source"),
        );
        const response = await fetch(`${source}/api/docupdates/${match[1]}`, {
          signal: controller.signal,
          credentials: "omit",
          cache: "no-store",
        });
        if (response.status === 410)
          throw new Error(
            "This update link has expired. Ask the practice for a new update.",
          );
        if (response.status === 404)
          throw new Error(
            "This authorization update was not found. Check the link with the practice.",
          );
        if (!response.ok)
          throw new Error("ATP could not load this update. Please try again.");
        const parsed = parseRecord(await response.json());
        if (mounted) setRecord(parsed);
      } catch (cause) {
        if (!mounted) return;
        setError(
          cause instanceof TypeError ||
            (cause instanceof Error && cause.name === "AbortError")
            ? "ATP is currently unreachable. Keep ATP and its HTTPS tunnel running, then try again."
            : cause instanceof Error
              ? cause.message
              : "The authorization update could not be loaded.",
        );
      } finally {
        clearTimeout(timeout);
      }
    }
    void load();
    return () => {
      mounted = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);
  if (record) return <App record={record} />;
  return (
    <>
      <header className="header">
        <div className="header-inner">
          <Brand />
        </div>
      </header>
      <main className="unavailable" aria-live="polite">
        <FileText size={40} />
        <h1>
          {error
            ? "This update isn’t available."
            : "Opening your authorization update…"}
        </h1>
        <p>
          {error ||
            "Connecting to ATP to retrieve this patient’s completed authorization."}
        </p>
        {error && (
          <button
            className="primary-button"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Try again <ArrowRight size={18} />
          </button>
        )}
      </main>
    </>
  );
}

function App({ record }: { record: AuthorizationRecord }) {
  const live = record.source === "atp";
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState("");
  async function downloadPdf() {
    if (pdfBusy) return;
    setPdfBusy(true);
    setPdfError("");
    try {
      const { createDocument } = await import("./document.mjs");
      const bytes = await createDocument(record);
      const url = URL.createObjectURL(
        new Blob([new Uint8Array(bytes)], { type: "application/pdf" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `DocUpdates-${record.callId || sample.token}.pdf`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch {
      setPdfError(
        "The PDF could not be generated. You can still view the complete document here.",
      );
    } finally {
      setPdfBusy(false);
    }
  }
  const dialog = useRef<HTMLDialogElement>(null);
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState(false);
  const directUrl = `${location.origin}${updatePath}`;
  async function copyLink() {
    try {
      await navigator.clipboard.writeText(directUrl);
      setCopied(true);
      setCopyError(false);
    } catch {
      setCopyError(true);
    }
  }
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to authorization
      </a>
      <header className="header">
        <div className="header-inner">
          <Brand />
          <nav aria-label="Main navigation">
            <a className={!isDemo ? "active" : ""} href={updatePath}>
              Authorization
            </a>
            <a href={`${updatePath}#documents`}>Documents</a>
            <a className="demo-button" href="/demo">
              <MessageSquare size={15} /> Text demo <ArrowUpRight size={14} />
            </a>
          </nav>
        </div>
      </header>
      {isDemo ? (
        <main id="main" className="sms-page">
          <a className="back-link" href={updatePath}>
            <ChevronLeft size={16} /> Back to authorization
          </a>
          <div className="sms-layout">
            <div>
              <p className="eyebrow cyan">FROM A TEXT TO THE NEXT STEP</p>
              <h1>
                Good news.
                <br />
                One tap away.
              </h1>
              <p className="sms-intro">
                An authorization is complete. Your doctor gets a text, opens the
                link, and has everything they need.
              </p>
              <span className="demo-label">SIMULATED TEXT MESSAGE</span>
              <p className="sms-note">
                This preview uses fictional data and does not send an SMS.
              </p>
            </div>
            <section className="phone" aria-label="Example doctor text message">
              <div className="phone-top">
                <span>2:42</span>
                <span>••• ▰</span>
              </div>
              <div className="phone-contact">
                <span className="contact-icon">
                  <MessageSquare size={23} />
                </span>
                <strong>DocUpdates</strong>
                <span>Text Message · SMS</span>
              </div>
              <p className="message-time">Today, 2:42 PM</p>
              <div className="message-bubble">
                DocUpdates: A prior authorization update is ready for your
                patient. View the decision, next steps, and approval document:
                <a href={updatePath}>{directUrl}</a>
              </div>
              <a className="phone-link" href={updatePath}>
                Open authorization update <ArrowRight size={17} />
              </a>
              <div className="phone-bottom" />
            </section>
          </div>
        </main>
      ) : (
        <>
          <section className="hero">
            <div className="hero-inner">
              <div>
                <div className="hero-kicker">
                  <span className="status-dot" /> AUTHORIZATION COMPLETE{" "}
                  <span className="hero-kicker-line" /> DOCUPDATES
                </div>
                <h1>
                  Prior Authorization
                  <br />
                  <span>Approved</span>
                  <CheckCircle2 className="hero-check" aria-hidden="true" />
                </h1>
                <p>One less barrier. One step closer to treatment.</p>
              </div>
              <div className="completion">
                <span className="completion-icon">
                  <Check size={23} />
                </span>
                <span>Completed on</span>
                <time dateTime={record.completedAt}>
                  {record.completedDate}
                  <small>{record.completedTime}</small>
                </time>
                <a href="#documents">
                  View approval document <ArrowDown size={16} />
                </a>
              </div>
            </div>
          </section>
          <main id="main" className="content">
            <div className="context-bar">
              <span>
                <span className="context-dot" /> PATIENT UPDATE
              </span>
              <span className="demo-label">DEMO · FICTIONAL PATIENT</span>
            </div>
            <section className="patient" aria-labelledby="patient-name">
              <div className="patient-name">
                <span className="avatar">{record.initials}</span>
                <div>
                  <span className="small-label">PATIENT</span>
                  <h2 id="patient-name">{record.patient}</h2>
                </div>
              </div>
              <dl className="patient-info">
                <div>
                  <dt>Date of birth</dt>
                  <dd>
                    {record.birthDate}
                    {record.age !== null && <span> · {record.age} years</span>}
                  </dd>
                </div>
                <div>
                  <dt>Member ID</dt>
                  <dd>{record.memberId}</dd>
                </div>
                <div>
                  <dt>Prescribing clinician</dt>
                  <dd>
                    {record.provider}
                    <small>{record.practice}</small>
                  </dd>
                </div>
              </dl>
            </section>
            <div className="main-grid">
              <div className="details-column">
                <section
                  className="medication section"
                  aria-labelledby="medication-title"
                >
                  <div className="section-heading">
                    <h2 id="medication-title">Medication & authorization</h2>
                    <Pill size={21} />
                  </div>
                  <div className="medication-title">
                    <h3>{record.medication}</h3>
                    <span>{record.generic}</span>
                  </div>
                  <p className="strength">{record.strength}</p>
                  <dl className="details-grid">
                    <div>
                      <dt>Prescribed dose</dt>
                      <dd>{record.dose}</dd>
                    </div>
                    <div>
                      <dt>Approved quantity</dt>
                      <dd>{record.quantity}</dd>
                    </div>
                    <div>
                      <dt>Insurance plan</dt>
                      <dd>{record.payer}</dd>
                    </div>
                    <div>
                      <dt>Authorization number</dt>
                      <dd className="reference">{record.authorizationId}</dd>
                    </div>
                  </dl>
                  <div className="coverage">
                    <span>
                      <CheckCircle2 size={17} /> Coverage period
                    </span>
                    <strong>
                      {record.coveragePeriod || (
                        <>
                          {record.coverageStart} <ArrowRight size={14} />{" "}
                          {record.coverageEnd}
                        </>
                      )}
                    </strong>
                  </div>
                </section>
                <section
                  id="documents"
                  className="documents section"
                  aria-labelledby="documents-title"
                >
                  <div className="section-heading">
                    <h2 id="documents-title">Authorization Documents</h2>
                    <span className="count">1</span>
                  </div>
                  <p>
                    Your approval, ready to view or save to the patient’s chart.
                  </p>
                  <div className="document-row">
                    <div className="file-icon">
                      <FileText size={25} />
                      <span>PDF</span>
                    </div>
                    <div className="document-info">
                      <h3>
                        {record.documentTitle || "Approved authorization"}
                      </h3>
                      <p>
                        {record.authorizationId}
                        {!live && " · 1 page"}
                      </p>
                      <span>
                        {live
                          ? "From your completed ATP call"
                          : "Mock payer approval letter"}
                      </span>
                    </div>
                    <button
                      className="view-button"
                      onClick={() => dialog.current?.showModal()}
                    >
                      View <ArrowUpRight size={16} />
                    </button>
                  </div>
                  <button
                    className="download-link"
                    onClick={downloadPdf}
                    disabled={pdfBusy}
                  >
                    <Download size={15} />
                    {pdfBusy ? "Preparing PDF…" : "Download PDF"}
                  </button>
                  {pdfError && <p role="alert">{pdfError}</p>}
                </section>
              </div>
              <aside className="summary">
                <p className="eyebrow">THE UPDATE, SIMPLIFIED</p>
                <h2>
                  Ready for the <br />
                  next step.
                </h2>
                <p>{record.summary}</p>
                <div className="next-step">
                  <span className="step-number">1</span>
                  <div>
                    <h3>
                      {live
                        ? "Next steps from the call"
                        : "Coordinate with the pharmacy"}
                    </h3>
                    <p>{record.nextStep}</p>
                  </div>
                </div>
                <div className="summary-note">
                  <CheckCircle2 size={17} />
                  <span>
                    {live
                      ? "Approval confirmed from the payer’s recorded response."
                      : "No additional clinical information is needed for this authorization."}
                  </span>
                </div>
                <p className="fine-print">
                  Approval confirms coverage authorization. Medication
                  dispensing and the patient’s final copay still need pharmacy
                  confirmation.
                </p>
              </aside>
            </div>
            <div className="endnote">
              <span>Less searching. More time for your patients.</span>
              <button onClick={copyLink}>
                <Copy size={15} />
                {copied ? "Link copied" : "Copy update link"}
              </button>
              <span role="status" className="copy-status">
                {copied
                  ? "Patient update link copied to clipboard."
                  : copyError
                    ? `Copy this link: ${directUrl}`
                    : ""}
              </span>
            </div>
          </main>
        </>
      )}
      <footer className="site-footer">
        <div>
          <span className="footer-product">DocUpdates</span>
          <span>A simpler connection to patient care.</span>
        </div>
        <p>
          {live
            ? "Connected to ATP · Synthetic demo · Call-specific update"
            : "Hackathon concept · Fictional sample data"}
        </p>
        <a href="https://www.impiricus.com/" target="_blank" rel="noreferrer">
          Explore Impiricus <ArrowUpRight size={14} />
        </a>
      </footer>
      <dialog
        ref={dialog}
        className="document-dialog"
        onClick={(e) => {
          if (e.target === e.currentTarget) dialog.current?.close();
        }}
        aria-labelledby="dialog-title"
      >
        <div className="dialog-toolbar">
          <div>
            <FileText size={18} />
            <h2 id="dialog-title">Authorization document</h2>
          </div>
          <div>
            <button
              onClick={downloadPdf}
              disabled={pdfBusy}
              className="dialog-download"
              aria-label="Download approval PDF"
            >
              <Download size={17} />
              <span>{pdfBusy ? "Preparing…" : "Download PDF"}</span>
            </button>
            <button
              aria-label="Close document"
              onClick={() => dialog.current?.close()}
            >
              <X size={21} />
            </button>
          </div>
        </div>
        <div className="document-body">
          <Form record={record} />
          {pdfError && <p role="alert">{pdfError}</p>}
        </div>
      </dialog>
    </>
  );
}
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Reader />
  </StrictMode>,
);
