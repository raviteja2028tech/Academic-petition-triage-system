// Browser end-to-end test of the React app against a RUNNING stack (default http://localhost:8080).
// Run it with any Playwright-compatible runner that default-exports `async (page) => result`, e.g. the browser-automation runner:
//   node <runner>/browser.mjs http://localhost:8080/ --script e2e/petition_flow.mjs
// It creates one synthetic petition (SYN-000555), one tiny PDF upload and one examiner decision, so run it against a THROWAWAY
// stack (a clean-copy install), not a database you care about. Set E2E_PDF to a small PDF path.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const BASE = process.env.E2E_BASE ?? "http://localhost:8080";
const steps = [];
const ok = (name, pass, detail = "") => { steps.push({ name, pass: Boolean(pass), detail: String(detail).slice(0, 200) }); };

export default async function run(page) {
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text().slice(0, 200)); });
  page.on("pageerror", (e) => consoleErrors.push("pageerror: " + String(e).slice(0, 200)));
  await page.setViewportSize({ width: 1366, height: 900 });

  const pdf = path.join(os.tmpdir(), "e2e-certificate.pdf");
  fs.writeFileSync(pdf, "%PDF-1.4\n% synthetic e2e document\n%%EOF\n");

  // ---------- Student: validation, then a valid submission with an upload
  await page.goto(`${BASE}/student/new`, { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /submit petition/i }).click();
  ok("empty form shows inline validation errors", (await page.getByRole("alert").count()) > 0);

  await page.getByLabel(/^student reference/i).fill("SYN-000555");
  await page.getByLabel(/^programme/i).fill("Computer Science");
  await page.getByLabel(/course code/i).fill("CS101");
  await page.getByLabel(/classes held/i).fill("100");
  await page.getByLabel(/classes attended/i).fill("80");
  ok("attendance percentage is calculated", await page.getByText("80%", { exact: true }).first().isVisible());
  await page.getByLabel(/describe your situation/i).fill("I was hospitalised for three weeks and request consideration of my attendance shortage.");
  await page.setInputFiles("#files", pdf);
  await page.getByRole("button", { name: /submit petition/i }).click();
  await page.waitForSelector("text=We have your petition", { timeout: 30000 });
  const runId = (await page.locator("p.font-mono").first().innerText()).trim();
  ok("submission confirmed with a run id", /^run_[0-9a-f]+$/.test(runId), runId);

  // ---------- Student: track until the AI finishes
  await page.getByRole("button", { name: /track this petition/i }).click();
  await page.waitForSelector("text=A human examiner must review this petition", { timeout: 240000 });
  const body = await page.locator("main").innerText();
  ok("AI recommendation shown and labelled 'not a decision'", /not a decision/i.test(body));
  ok("human review is stated as required", /A human examiner must review this petition/.test(body));
  ok("no human decision yet", /No human decision yet/.test(body));
  ok("uploaded document is listed", /e2e-certificate\.pdf/.test(body));
  const mobile = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  ok("no horizontal overflow on desktop", !mobile);

  // ---------- Examiner: queue -> review -> decision
  await page.getByRole("button", { name: /examiner/i }).first().click();
  await page.waitForSelector("text=Review dashboard");
  await page.getByRole("link", { name: /petition queue/i }).click();
  await page.getByPlaceholder(/student, course or run id/i).fill(runId);
  await page.getByRole("link", { name: new RegExp(runId) }).first().click();
  await page.waitForSelector("text=Petition as submitted");
  ok("examiner sees the student's petition and document", /SYN-000555|CS101/.test(await page.locator("main").innerText()) && (await page.getByRole("link", { name: /download/i }).count()) > 0);

  await page.getByRole("button", { name: /record my decision/i }).click();
  ok("decision form refuses an empty submission", (await page.getByText(/Choose a decision/).count()) > 0);
  await page.getByLabel(/your name or initials/i).fill("E2E Test Examiner");
  await page.getByRole("radio", { name: /more information requested/i }).click();
  await page.getByLabel(/your reasoning/i).fill("E2E test: please provide the original certificate dates.");
  await page.getByRole("button", { name: /record my decision/i }).click();
  await page.waitForSelector("text=Decision history >> xpath=.. >> text=E2E Test Examiner", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const rv = await page.locator("main").innerText();
  ok("decision recorded and shown in history, separate from the AI recommendation", /E2E Test Examiner/.test(rv) && /More information requested/.test(rv) && /AI recommendation/.test(rv));

  // ---------- Student sees the human decision
  await page.goto(`${BASE}/student/petitions/${runId}`, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Human examiner decision");
  const sv = await page.locator("main").innerText();
  ok("student sees the examiner's decision and note", /More information requested/.test(sv) && /original certificate dates/.test(sv));

  // ---------- System portal renders real numbers
  await page.goto(`${BASE}/monitor`, { waitUntil: "networkidle" });
  await page.waitForSelector("text=Service health");
  ok("system overview renders", /Redis/.test(await page.locator("main").innerText()));

  // ---------- Mobile
  await page.setViewportSize({ width: 390, height: 844 });
  for (const p of ["/student/new", "/examiner", `/examiner/review/${runId}`]) {
    await page.goto(`${BASE}${p}`, { waitUntil: "networkidle" });
    await page.waitForTimeout(800);
    const over = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    ok(`mobile 390px: no horizontal scroll on ${p.replace(runId, ":id")}`, !over);
  }
  await page.getByRole("button", { name: /open menu/i }).click();
  ok("mobile navigation drawer opens", await page.getByRole("navigation", { name: "Primary" }).isVisible());

  ok("no browser console errors", consoleErrors.length === 0, consoleErrors.join(" | "));
  return { passed: steps.filter((s) => s.pass).length, total: steps.length, runId, steps };
}
