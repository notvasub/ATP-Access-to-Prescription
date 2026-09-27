# DocUpdates

The hosted approval reader for ATP, using Impiricus branding. ATP completes the call, verifies the final payer decision, saves a call-specific summary, and posts the unique DocUpdates link through its notification channel. The current ATP notification integration uses Slack.

Sample approval: https://docupdates.vercel.app/u/du_7f3a9c2e8b614d05

Sample text-message walkthrough: https://docupdates.vercel.app/demo

## Connected flow

1. Run ATP with `make demo` and keep the backend and its HTTPS tunnel running.
2. Complete a phone call with an explicit final payer approval. After audio teardown, ATP checks the frozen transcript; pending, denied, failed, interrupted, or unverified outcomes do not produce an approval notification.
3. ATP persists a snapshot with the case's patient, medication, clinician, and the payer-confirmed authorization reference, coverage, and next steps. Missing payer details stay marked as unspecified.
4. The notification contains a URL such as `/u/<random-token>?source=<ATP-HTTPS-origin>`. It opens this reader directly, without a login. No patient information is embedded in the URL.
5. DocUpdates retrieves only that summary from `/api/docupdates/<token>`. It does not get the full transcript, contacts, source chart, or operator access. The record survives a new call and backend restarts in ATP's SQLite database; the link expires after seven days.
6. The clinician can view or download a PDF of the **ATP authorization completion summary**. It is labeled as generated from the call, not a payer-issued approval letter.

ATP's operator view and call history show the notification status and the approval link. A notification failure preserves the link for manual sharing. There is at most one automatic notification attempt per call; restarting ATP never silently resends it. Browser rehearsal creates a link but does not post a notification.

## Run the reader locally

```sh
npm ci
npm run dev
npm run build
npm run preview
```

The build checks TypeScript and generates the static sample PDF from `src/authorization.json`. The live HTML and PDF use the fetched record, and `src/document.mjs` handles wrapping and additional PDF pages for longer details.

The sample URL and `/demo` remain fictional examples, independent of call records. Connected URLs never fall back to the sample patient. Invalid, expired, missing, and unreachable updates show an explicit error with a retry control.

## Connection settings

- ATP: `DOCUPDATES_BASE_URL=https://docupdates.vercel.app` (default). Blank disables automatic completion updates.
- ATP: `PUBLIC_BASE_URL` may supply a stable HTTPS backend origin; otherwise `make demo` supplies its Cloudflare Quick Tunnel origin.
- Reader: Cloudflare Quick Tunnel origins are accepted by default. For a custom stable backend origin, set `VITE_ATP_BASE_URL` to that exact HTTPS origin and rebuild/redeploy.
- ATP allows cross-origin reads only from the configured DocUpdates origin. To use a locally hosted reader, serve it through HTTPS and use that origin in `DOCUPDATES_BASE_URL`.

The source query parameter survives navigation to documents and copied links. Fetches omit credentials and use `no-store`. Do not stop the tunnel during the presentation: a stopped/replaced tunnel makes its existing links unreachable even if the saved record has not expired.

## Demo boundary

Use synthetic data only. This is a hackathon integration, not a production patient portal or a clinical decision system. The final review uses an LLM and must still be checked against the call. The random link grants read access to one summary and should be shared only with intended recipients. Actual payer-issued forms are not fetched; the connected document is an ATP-generated summary. The sample page contains a clearly labeled mock payer letter.

## Hosting

Only this directory is deployed to Vercel; ATP's credentials, database, and call backend remain outside the upload root. `vercel.json` supplies direct-route fallback and no-index headers. The browser contacts ATP's HTTPS endpoint only for connected records.

Deploy from this directory with `vercel --prod`. `.vercel/project.json` identifies the linked project. Brand reference: https://www.impiricus.com/.
