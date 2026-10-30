// npm install --no-save playwright; install Chrome or set PLAYWRIGHT_CHANNEL.
// Use a temporary synthetic workspace. Never capture real customer data for Git.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');

(async () => {
  const output = path.resolve(__dirname, '../docs/screenshots');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1512, height: 1050}, reducedMotion: 'reduce'});
    const page = await context.newPage();
    page.setDefaultTimeout(60000);
    async function settled() {
      await page.getByRole('button', {name: 'Stop', exact: true}).waitFor({state: 'hidden', timeout: 120000});
      await page.waitForTimeout(800);
      if (await page.getByTestId('stException').count()) throw new Error('Application exception detected');
    }
    async function capture(name) {
      await settled();
      if (name !== '03-analytics-details.png') await page.evaluate(() => document.querySelector('[data-testid="stMain"]')?.scrollTo(0, 0));
      await page.screenshot({path: path.join(output, name), fullPage: true});
      console.log('Captured ' + name);
    }
    async function navigate(name) {
      await page.getByText(name, {exact: true}).first().click();
      await settled();
    }
    await page.goto(process.env.CORTEX_URL || 'http://127.0.0.1:8501');
    await page.getByRole('heading', {name: 'Your intelligence workspace'}).waitFor();
    await capture('01-sign-in.png');
    await page.getByRole('tab', {name: 'Create account'}).click();
    const suffix = crypto.randomBytes(8).toString('hex');
    const password = crypto.randomBytes(24).toString('hex');
    await page.getByRole('textbox', {name: 'Work email', exact: true}).fill(`capture-${suffix}@example.test`);
    await page.getByRole('textbox', {name: 'Create password', exact: true}).fill(password);
    await page.getByRole('textbox', {name: 'Confirm password', exact: true}).fill(password);
    await page.getByText('I have read the privacy notice and am authorized to upload this data.', {exact: true}).click();
    await page.getByRole('button', {name: 'Create workspace', exact: true}).click();
    await page.getByRole('button', {name: 'Load demonstration workspace'}).waitFor();
    await page.getByRole('button', {name: 'Load demonstration workspace'}).click();
    await page.getByText('Revenue over time', {exact: true}).waitFor();
    await capture('02-overview.png');
    await page.getByText('Unit economics by product', {exact: true}).scrollIntoViewIfNeeded();
    await capture('03-analytics-details.png');
    await navigate('Reports');
    await page.getByText('Reports that reconcile', {exact: true}).waitFor();
    await capture('04-reports.png');
    await navigate('Data studio');
    await capture('05-data-studio.png');
    await page.getByRole('tab', {name: 'Dataset registry'}).click();
    await page.getByText('demo-policies.txt · document · uploaded', {exact: true}).click();
    await page.getByTestId('stExpander').filter({hasText: 'demo-policies.txt'}).getByRole('button', {name: 'Build selected index'}).click();
    await page.getByText(/Ready: \d+ chunks/).waitFor();
    await capture('06-index-registry.png');
    await navigate('Knowledge');
    await page.getByRole('textbox', {name: 'Search your knowledge'}).fill('How long does a refund take?');
    await page.getByRole('button', {name: 'Find evidence'}).click();
    await page.getByText(/Refunds are processed within 5 business days/).first().waitFor();
    await capture('07-knowledge.png');
    await navigate('AI copilot');
    const input = page.getByTestId('stChatInputTextArea');
    await input.fill('How long does a refund take?');
    await input.press('Enter');
    await page.getByText('Was this answer useful?', {exact: true}).waitFor();
    await capture('08-copilot.png');
    await navigate('Operations');
    await capture('09-operations.png');
    await navigate('Integrations');
    await capture('10-integrations.png');
    await navigate('Governance');
    await capture('11-governance.png');
    await navigate('Overview');
    await page.setViewportSize({width: 390, height: 844});
    await page.evaluate(() => document.querySelector('[data-testid="stMain"]')?.scrollTo(0, 0));
    await settled();
    await page.screenshot({path: path.join(output, '12-mobile.png'), fullPage: true});
    console.log('Captured 12-mobile.png');
    // Remove demonstration content from active storage after capturing.
    await page.setViewportSize({width: 1512, height: 1050});
    await navigate('Governance');
    await page.getByRole('textbox', {name: 'Type ERASE MY WORKSPACE to remove your data'}).fill('ERASE MY WORKSPACE');
    await page.getByRole('textbox', {name: 'Type ERASE MY WORKSPACE to remove your data'}).press('Enter');
    await settled();
    await page.getByRole('button', {name: 'Erase workspace content'}).click();
    await settled();
    await context.close();
  } finally { await browser.close(); }
})().catch(error => {console.error(error.message); process.exitCode = 1;});
