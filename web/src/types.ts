export type Role =
  "operator" | "administrator" | "doctor" | "presentation" | "payer";
export type Session = {
  role: Role;
  call_id?: string;
  identity?: string;
  phone_control?: boolean;
};
export type Case = {
  id: string;
  patient: string;
  date_of_birth: string;
  member_id: string;
  provider: string;
  provider_npi: string;
  practice: string;
  medication: string;
  dose: string;
  payer: string;
  diagnosis: string;
  request: string;
  evidence: string;
};
export type Turn = {
  id: string;
  speaker: string;
  text: string;
  time: number;
  interrupted: boolean;
};
export type Fact = {
  value: string;
  source: string;
  evidence_turn_ids: string[];
};
export type Call = {
  id: string;
  room: string;
  mode: string;
  scenario?: "standard" | "pitch";
  approval_notification_status?: string;
  status: string;
  control: string;
  revision: number;
  sequence: number;
  created_at: number;
  answered_at: number | null;
  ended_at: number | null;
  agent_status: string;
  transcript: Turn[];
  facts: Record<string, Fact>;
  events: { time: number; text: string }[];
  briefing?: { role: string; reason: string; summary: string } | null;
  error: string | null;
  participants: Record<string, { role: string; connected: boolean }>;
  case: Case;
  controller_identity?: string;
  docupdates?: {
    state: string;
    notification_status?: string;
    notification_provider?: string;
    sms_status?: string;
    url?: string;
    error?: string;
    outcome?: string;
  };
  doctor_call?: {
    identity: string;
    status: string;
    notification_provider?: string;
    notification_status?: string;
    notification_error?: string;
    sms_status?: string; // Older call history
    sms_error?: string;
    error?: string;
    control_url?: string;
    briefing?: { reason: string; summary: string };
  } | null;
};
export type Checks = Record<string, { ok: boolean; detail: string }>;

export type Contacts = {
  insurer_phone_number: string;
  doctor_phone_number: string;
};
