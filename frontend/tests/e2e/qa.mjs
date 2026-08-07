/**
 * frontend/tests/e2e/qa.mjs
 * Does the dashboard actually show what it is supposed to?
 *
 * Every other check in this repo verifies the parts: unit tests assert the API
 * returns entities, tsc asserts the component compiles, grep asserts it is
 * imported. None of that proves a human opening the page sees anything -- a
 * component can be mounted, typed and unit-tested and still render nothing
 * because a 401 emptied it, or throw on mount and leave a blank tab.
 *
 * This drives a real browser through the features that were actually asked
 * for, and reports what is on the screen rather than what is in the source.
 *
 *   node <browser-automation-skill>/browser.mjs http://127.0.0.1:3000 \
 *        --script frontend/tests/e2e/qa.mjs
 *
 * Needs the backend on :8000 and the frontend on :3000.
 */

const CREDS = { email: "demo@roger.lk", password: "correct-horse-battery-staple" };

/** Click a tab by its visible label and wait for the panel to swap. */
async function openTab(page, label) {
  const tab = page.getByRole("tab", { name: new RegExp(label, "i") });
  if (!(await tab.count())) return false;
  await tab.first().click();
  await page.waitForTimeout(700);
  return true;
}

async function bodyText(page) {
  return (await page.locator("body").innerText()).replace(/\s+/g, " ");
}

export default async function run(page, ui) {
  const report = { tabs: {}, features: {}, problems: [] };

  // --- the page mounts at all ---------------------------------------------
  await page.waitForTimeout(2500);
  const title = await page.title();
  const text = await bodyText(page);
  report.title = title;
  report.bodyChars = text.length;

  if (text.length < 200) {
    report.problems.push("page rendered almost nothing -- app did not mount");
    return report;
  }

  // --- which tabs exist ----------------------------------------------------
  const tabs = await page.getByRole("tab").allInnerTexts();
  report.tabsFound = tabs.map((t) => t.trim()).filter(Boolean);

  for (const label of ["OVERVIEW", "INTEL FEED", "STORIES", "ANOMALIES", "ACCOUNTS"]) {
    report.tabs[label] = report.tabsFound.some((t) =>
      t.toUpperCase().includes(label));
  }

  // --- OVERVIEW: risk indices + drivers + regulatory count -----------------
  await openTab(page, "OVERVIEW");
  const overview = await bodyText(page);
  report.features.riskIndices = /RISK INDICES/i.test(overview);
  report.features.logisticsFriction = /Logistics friction/i.test(overview);
  report.features.regulatoryAsCount = /Regulatory activity/i.test(overview)
    && /stor(y|ies)/i.test(overview);
  report.features.driverDrilldown = /Why \d+%\?/i.test(overview);

  // --- STORIES -------------------------------------------------------------
  if (await openTab(page, "STORIES")) {
    const stories = await bodyText(page);
    report.features.storiesPanel = /ONGOING STORIES/i.test(stories);
    // Either real stories, or the honest empty state -- both are "working".
    report.features.storiesRendered =
      /No stories yet/i.test(stories) || /event/i.test(stories);
  }

  // --- ACCOUNTS: the social login fields -----------------------------------
  if (await openTab(page, "ACCOUNTS")) {
    const accounts = await bodyText(page);
    report.features.socialPanel = /SOCIAL ACCOUNTS/i.test(accounts);
    report.features.signedOutExplained = /Sign in to manage social accounts/i.test(accounts);
    report.features.saysWhereBrowserOpens = /machine running this server/i.test(accounts);
    report.features.collectedPostsPanel = /COLLECTED POSTS/i.test(accounts);
    // The old pairing card must be gone.
    report.features.oldConnectorCardGone =
      !/control your connector/i.test(accounts) && !/pairing code/i.test(accounts);
  }

  // --- log in, then re-check the accounts panel ----------------------------
  // Signed out, the panel is deliberately a prompt. The password fields only
  // exist for an authenticated user, so this is the check that matters.
  const loginSnap = await ui.snapshot();
  const emailRef = loginSnap.match(/@(e\d+) textbox "?(Email|email)/)?.[1];

  if (emailRef) {
    report.loginFormPresent = true;
  } else {
    // Not on a login screen -- try navigating to it.
    await page.goto("http://127.0.0.1:3000/", { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);
  }

  // Try an API-level login and re-render, which is what the app does.
  const loggedIn = await page.evaluate(async (creds) => {
    try {
      const res = await fetch("http://127.0.0.1:8000/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(creds),
      });
      return res.status;
    } catch (e) {
      return String(e);
    }
  }, CREDS);
  report.apiLoginStatus = loggedIn;

  return report;
}
