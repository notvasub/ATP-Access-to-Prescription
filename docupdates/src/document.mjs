import { PDFDocument, StandardFonts, rgb } from "pdf-lib";

// Shared by the sample build and the live reader. Layout grows for longer call details.
export async function createDocument(record) {
  const pdf = await PDFDocument.create();
  const live = record.source === "atp";
  pdf.setTitle(
    `${live ? "ATP call summary" : "MOCK approval"} - ${record.authorizationId}`,
  );
  pdf.setAuthor("DocUpdates - ATP hackathon demo");
  const regular = await pdf.embedFont(StandardFonts.Helvetica);
  const bold = await pdf.embedFont(StandardFonts.HelveticaBold);
  const ink = rgb(0.16, 0.21, 0.18),
    muted = rgb(0.43, 0.48, 0.44),
    green = rgb(0.17, 0.38, 0.29);
  let page = pdf.addPage([612, 792]);
  let y = 744;
  function text(value, x, at, size = 10, font = regular, color = ink) {
    page.drawText(value, { x, y: at, size, font, color });
  }
  function ensure(height) {
    if (y - height < 90) {
      page = pdf.addPage([612, 792]);
      y = 744;
    }
  }
  function lines(value, width, size = 10, font = regular) {
    const output = [];
    let current = "";
    for (const char of String(value).replace(/\s+/g, " ").trim()) {
      if (font.widthOfTextAtSize(current + char, size) > width) {
        const space = current.lastIndexOf(" ");
        if (space > 0) {
          output.push(current.slice(0, space));
          current = current.slice(space + 1) + char;
        } else {
          output.push(current);
          current = char;
        }
      } else current += char;
    }
    if (current) output.push(current);
    return output;
  }
  function paragraph(value, size = 10, color = ink) {
    for (const line of lines(value, 520, size)) {
      ensure(16);
      text(line, 46, y, size, regular, color);
      y -= 15;
    }
    y -= 8;
  }
  function heading(value) {
    ensure(66);
    y -= 13;
    text(value, 46, y, 12, bold);
    y -= 10;
    page.drawLine({
      start: { x: 46, y },
      end: { x: 566, y },
      thickness: 0.6,
      color: rgb(0.84, 0.87, 0.83),
    });
    y -= 21;
  }
  function pair(left, right) {
    const a = lines(left[1], 245),
      b = lines(right[1], 245);
    const height = 18 + Math.max(a.length, b.length) * 14 + 13;
    ensure(height);
    text(left[0].toUpperCase(), 46, y, 7.5, regular, muted);
    text(right[0].toUpperCase(), 316, y, 7.5, regular, muted);
    a.forEach((line, i) => text(line, 46, y - 17 - i * 14));
    b.forEach((line, i) => text(line, 316, y - 17 - i * 14));
    y -= height;
  }
  text(live ? "DOCUPDATES / ATP" : "MERIDIAN BENEFITS", 46, y, 18, bold, green);
  text(live ? "ATP CALL SUMMARY" : "MOCK DOCUMENT", 450, y, 8, bold, muted);
  y -= 23;
  paragraph(
    live
      ? "Authorization completion summary"
      : "Pharmacy Services | Coverage Determination",
    10,
    muted,
  );
  y -= 12;
  text("Prior Authorization Approved", 46, y, 23, bold);
  y -= 25;
  paragraph(
    `Completed ${record.completedDate} at ${record.completedTime}`,
    10,
    muted,
  );
  y -= 6;
  paragraph(`Reference: ${record.authorizationId}`, 10, green);
  heading("Member & prescriber information");
  pair(["Patient name", record.patient], ["Date of birth", record.birthDate]);
  pair(
    ["Member ID", record.memberId],
    ["Prescribing clinician", record.provider],
  );
  pair(["Practice", record.practice], ["Diagnosis", record.diagnosis]);
  heading("Medication & coverage");
  pair(
    [
      "Medication",
      record.medication + (record.generic ? ` (${record.generic})` : ""),
    ],
    ["Prescribed dose", record.dose],
  );
  pair(
    ["Insurance plan", record.payer],
    ["Approved quantity", record.quantity],
  );
  pair(
    [
      "Coverage period",
      record.coveragePeriod ||
        `${record.coverageStart} - ${record.coverageEnd}`,
    ],
    [
      "Source",
      live ? `ATP call ${record.callId}` : "Fictional sample authorization",
    ],
  );
  heading("Determination & next steps");
  paragraph(record.summary);
  paragraph(record.nextStep);
  paragraph(
    live
      ? record.documentNote
      : "Mock payer approval letter. Not valid for clinical or billing use.",
    8,
    muted,
  );
  paragraph(
    "Approval does not confirm medication dispensing or the final out-of-pocket cost.",
    8,
    muted,
  );
  const pages = pdf.getPages();
  pages.forEach((sheet, index) => {
    sheet.drawLine({
      start: { x: 46, y: 65 },
      end: { x: 566, y: 65 },
      thickness: 0.6,
      color: rgb(0.84, 0.87, 0.83),
    });
    sheet.drawText("SYNTHETIC DEMO - NOT VALID FOR CLINICAL OR BILLING USE", {
      x: 46,
      y: 49,
      size: 8,
      font: bold,
      color: muted,
    });
    sheet.drawText(`Page ${index + 1} of ${pages.length}`, {
      x: 516,
      y: 35,
      size: 8,
      font: regular,
      color: muted,
    });
  });
  return pdf.save();
}
