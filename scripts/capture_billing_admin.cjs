// Demonstrates individual tester promotion and billing authorization in isolated QA only.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path');
(async()=>{
 const root=path.resolve(__dirname,'..'),qa=JSON.parse(fs.readFileSync(path.join(root,'data/private/account-capture/credentials.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  async function login(context,email,password,next){
   const page=await context.newPage();page.setDefaultTimeout(60000);
   await page.goto('http://localhost:8513/billing/login?next='+encodeURIComponent(next));
   await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);
   await Promise.all([page.waitForURL('**'+next),page.getByRole('button',{name:'Sign in to billing',exact:true}).click()]);
   return page;
  }
  async function capture(page,name){await page.screenshot({path:path.join(root,'docs/screenshots',name),fullPage:true});console.log('Captured '+name);}
  const primary=await browser.newContext({viewport:{width:1512,height:1050}});
  const admin=await login(primary,qa.email,qa.password,'/admin');
  await admin.getByLabel('Your account password',{exact:true}).fill(qa.password);
  await admin.getByRole('button',{name:'Verify administrator',exact:true}).click();
  await admin.getByRole('heading',{name:'Admin Dashboard · User directory',exact:true}).waitFor();
  await admin.goto('http://localhost:8513/admin/users/'+qa.tester);
  await capture(admin,'34-admin-user-details.png');
  const role=admin.locator('form:has(input[name="action"][value="role"])');
  await role.locator('select[name="value"]').selectOption('super_admin');await role.getByRole('checkbox').check();
  await role.getByRole('button',{name:'Apply platform role',exact:true}).click();
  const testers=await browser.newContext({viewport:{width:1512,height:1050}});
  const tester=await login(testers,qa.tester_email,qa.tester_password,'/admin/billing');
  await tester.getByLabel('Your account password',{exact:true}).fill(qa.tester_password);
  await tester.getByRole('button',{name:'Verify administrator',exact:true}).click();
  await tester.getByRole('heading',{name:'Billing administration',exact:true}).waitFor();
  await capture(tester,'36-named-super-admin-billing.png');
  await tester.getByRole('button',{name:'Check Stripe configuration',exact:true}).click();
  await tester.getByRole('heading',{name:'Stripe configuration check',exact:true}).waitFor();
  const text=await tester.locator('main').innerText();
  if(!text.includes('"subscription_update": true'))throw new Error('Configured portal does not enable plan changes');
  await capture(tester,'37-stripe-configuration-check.png');
  await tester.goto('http://localhost:8513/pricing');
  if(await tester.getByRole('button',{name:'Choose monthly',exact:true}).count()!==3)throw new Error('Configured monthly pricing options missing');
  await capture(tester,'35-configured-subscription-plans.png');
  await tester.goto('http://localhost:8513/workspace/settings/billing');
  if(!await tester.getByRole('link',{name:'Choose or resume a subscription',exact:true}).count())throw new Error('Free account has no subscription purchase path');
  await admin.goto('http://localhost:8513/admin/users/'+qa.tester);
  const revoke=admin.locator('form:has(input[name="action"][value="role"])');
  await revoke.locator('select[name="value"]').selectOption('member');await revoke.getByRole('checkbox').check();
  await revoke.getByRole('button',{name:'Apply platform role',exact:true}).click();
  const response=await tester.goto('http://localhost:8513/admin/billing');
  if(new URL(tester.url()).pathname!=='/billing/login')throw new Error('Revoked tester retained billing access');
  console.log('Named tester promotion, independent password verification, billing diagnostics and immediate role revocation passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
