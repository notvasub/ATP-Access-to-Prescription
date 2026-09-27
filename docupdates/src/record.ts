import sample from "./authorization.json";

export type AuthorizationRecord = Omit<
  typeof sample,
  "token" | "documentPath" | "age"
> & {
  token?: string;
  documentPath?: string;
  age: number | null;
  source?: "atp";
  status?: "approved";
  callId?: string;
  coveragePeriod?: string;
  documentTitle?: string;
  documentNote?: string;
};

export function parseRecord(value: unknown): AuthorizationRecord {
  if (!value || typeof value !== "object")
    throw new Error("Invalid authorization response.");
  const data = value as Record<string, unknown>;
  const fields = [
    "patient",
    "initials",
    "birthDate",
    "memberId",
    "provider",
    "practice",
    "medication",
    "generic",
    "strength",
    "dose",
    "quantity",
    "payer",
    "authorizationId",
    "diagnosis",
    "completedAt",
    "completedDate",
    "completedTime",
    "summary",
    "nextStep",
    "coverageStart",
    "coverageEnd",
    "coveragePeriod",
    "documentTitle",
    "documentNote",
    "callId",
  ];
  if (
    data.source !== "atp" ||
    data.status !== "approved" ||
    fields.some((key) => typeof data[key] !== "string") ||
    !(data.age === null || typeof data.age === "number")
  ) {
    throw new Error("This response does not contain a confirmed ATP approval.");
  }
  return data as AuthorizationRecord;
}

export function readSource(raw: string | null): string {
  if (!raw)
    throw new Error(
      "This link is missing its ATP connection. Use the full link from the approval text.",
    );
  const url = new URL(raw);
  const configured = import.meta.env.VITE_ATP_BASE_URL as string | undefined;
  const allowed =
    /^https:\/\/[a-z0-9-]+\.trycloudflare\.com$/.test(url.origin) ||
    (configured && url.origin === new URL(configured).origin);
  if (
    !allowed ||
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    (url.pathname !== "/" && url.pathname !== "") ||
    url.search ||
    url.hash
  ) {
    throw new Error(
      "This ATP connection is not configured for DocUpdates. Ask the practice for an updated link.",
    );
  }
  return url.origin;
}
