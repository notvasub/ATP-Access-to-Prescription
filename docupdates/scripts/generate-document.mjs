import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createDocument } from "../src/document.mjs";
const record = JSON.parse(
  await readFile(new URL("../src/authorization.json", import.meta.url), "utf8"),
);
await mkdir(new URL("../public/documents/", import.meta.url), {
  recursive: true,
});
await writeFile(
  new URL(`../public/documents/${record.authorizationId}.pdf`, import.meta.url),
  await createDocument(record),
);
