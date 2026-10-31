// Capture real, unconfigured test-mode billing pages using a temporary account.
// Never add cards, provider keys, personal data or mocked paid states to screenshots.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const crypto = require('node:crypto');
(async () => {
  const root = path.resolve(__dirname, '..');
  const email = 'screenshot-billing-' + crypto.randomBytes(6).toString('hex') + '@example.test';
  const password = crypto.randomBytes(24).toString('hex');
  const signup = "import sys,json\nfrom dotenv import load_dotenv\nload_dotenv('.env')\nfrom cortex import store\nstore.initialize()\nparams=json.load(sys.stdin)\nstore.signup(params['email'],params['password'])\n";
  execFileSync(path.join(root,'.venv312/Scripts/python.exe'),['-c',signup],{cwd:root,input:JSON.stringify({email,password}),stdio:['pipe','pipe','pipe']});
  console.log('Opening capture browser');
  const browser = await chromium.launch({channel:'chrome',headless:true,timeout:60000});
  console.log('Capture browser ready');
  try {
    const context = await browser.newContext({viewport:{width:1512,height:1050}});
    const page = await context.newPage();
    page.setDefaultTimeout(120000);
    if (!process.env.CORTEX_BILLING_ONLY) {
    await page.goto('http://localhost:8501');
    console.log('Workspace loaded');
    await page.getByLabel('Email',{exact:true}).fill(email);
    await page.getByLabel('Password',{exact:true}).fill(password);
    await page.getByRole('button',{name:'Sign in',exact:true}).click();
    await page.getByText('Subscriptions',{exact:true}).first().waitFor();
    console.log('Workspace authenticated');
    await page.getByText('Subscriptions',{exact:true}).first().click();
    await page.getByRole('heading',{name:'Settings · Billing',exact:true}).waitFor();
    await page.getByRole('link',{name:'Plans & pricing',exact:true}).waitFor();
    await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});
    await page.waitForTimeout(1000);
    await page.screenshot({path:path.join(root,'docs/screenshots/15-subscriptions.png'),fullPage:true});
    console.log('Captured workspace billing');
    }
    await page.goto('http://localhost:8503/billing/login');
    await page.getByLabel('Email',{exact:true}).fill(email);
    await page.getByLabel('Password',{exact:true}).fill(password);
    const [loginResponse] = await Promise.all([page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/billing/login')),page.getByRole('button',{name:'Sign in to billing',exact:true}).click()]);
    console.log('Billing login HTTP:',loginResponse.status(),'origin:',await loginResponse.request().headerValue('origin'));
    if(loginResponse.status()!==303) throw new Error('Billing login rejected: '+(await loginResponse.text()).slice(0,300));
    await page.waitForURL('**/workspace/settings/billing');
    console.log('Billing sign-in result:',new URL(page.url()).pathname);
    if(new URL(page.url()).pathname !== '/workspace/settings/billing') throw new Error('Billing sign-in rejected: '+(await page.locator('body').innerText()).slice(0,400));
    const routes=[['/pricing','20-billing-pricing.png'],['/workspace/settings/billing','21-billing-overview.png'],['/workspace/settings/billing/payment-methods','22-billing-payment-methods.png'],['/workspace/settings/billing/invoices','23-billing-invoices.png'],['/workspace/settings/billing/usage','24-billing-usage.png']];
    for(const [route,name] of routes){
      const response=await page.goto('http://localhost:8503'+route);
      if(response.status()!==200) throw new Error('Billing capture HTTP '+response.status());
      await page.screenshot({path:path.join(root,'docs/screenshots',name),fullPage:true});
      console.log('Captured '+name);
    }
    await page.setViewportSize({width:390,height:844});
    await page.goto('http://localhost:8503/pricing');
    if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)) throw new Error('Mobile horizontal overflow');
    await page.screenshot({path:path.join(root,'docs/screenshots/25-billing-mobile.png'),fullPage:true});
  } finally {
    await browser.close();
    // Delete only this capture's generated identity and sessions. It has no uploads.
    const cleanup = `import sys\nfrom dotenv import load_dotenv\nload_dotenv('.env')\nfrom cortex import store\nstore.initialize()\nemail=sys.argv[1]\nassert email.startswith('screenshot-billing-') and email.endswith('@example.test')\nwith store.connection() as db:\n row=db.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()\n if row:\n  db.execute('DELETE FROM billing_sessions WHERE owner=?',(row[0],))\n  db.execute('DELETE FROM users WHERE id=?',(row[0],))\n`;
    execFileSync(path.join(root,'.venv312/Scripts/python.exe'),['-c',cleanup,email],{cwd:root,stdio:'pipe'});
  }
})().catch(error=>{console.error(error.message);process.exitCode=1;});
