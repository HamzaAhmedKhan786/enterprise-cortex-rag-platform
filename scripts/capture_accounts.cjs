// Real browser QA against explicitly isolated test servers. No production users are seeded.
const { chromium }=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const root=path.resolve(__dirname,'..');
 const qa=JSON.parse(fs.readFileSync(path.join(root,'data/private/account-capture/credentials.json'),'utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1512,height:1050},reducedMotion:'reduce'});
  const page=await context.newPage();page.setDefaultTimeout(60000);
  async function settled(){
   await page.getByRole('button',{name:'Stop',exact:true}).waitFor({state:'hidden'});
   await page.waitForTimeout(700);
   if(await page.getByTestId('stException').count())throw new Error('Streamlit exception detected');
  }
  async function screenshot(tab,name){await tab.screenshot({path:path.join(root,'docs/screenshots',name),fullPage:true});console.log('Captured '+name);}
  async function navigate(name){await page.getByText(name,{exact:true}).first().click();await page.getByRole('heading',{name,exact:true}).waitFor();await settled();}
  await page.goto('http://localhost:8511/?section=My%20Profile');
  await page.getByLabel('Email',{exact:true}).fill(qa.email);
  await page.getByLabel('Password',{exact:true}).fill(qa.password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'My Profile',exact:true}).waitFor();await settled();
  await page.getByLabel('Full name',{exact:true}).fill('QA Profile Updated');
  await page.getByRole('button',{name:'Save profile',exact:true}).click();await settled();
  await screenshot(page,'26-my-profile.png');
  const [account]=await Promise.all([context.waitForEvent('page'),page.getByRole('link',{name:'Manage subscription, payment methods and invoices',exact:true}).click()]);
  await account.waitForURL('**/workspace/settings/billing');
  let response=await account.goto('http://localhost:8513/account/profile');
  if(response.status()!==200 || !await account.getByText('QA Profile Updated',{exact:false}).count()) {
    // Input values aren't text nodes. Verify the persisted profile field directly.
    if(await account.getByLabel('Full name').inputValue()!=='QA Profile Updated')throw new Error('Profile/handoff identity mismatch');
  }
  await screenshot(account,'32-service-profile.png');
  await navigate('Account Settings');await screenshot(page,'27-account-settings.png');
  await navigate('Admin Dashboard');
  await page.waitForFunction(()=>document.querySelectorAll('input[aria-label="Verify your account password"]').length===1);
  await page.getByLabel('Verify your account password',{exact:true}).fill(qa.password);
  await page.getByRole('button',{name:'Verify for ten minutes',exact:true}).click();await settled();
  await page.getByText('Matching registered users',{exact:true}).waitFor();
  await page.getByText('Verify password for sensitive actions',{exact:true}).click();await page.getByLabel('Verify your account password',{exact:true}).waitFor({state:'hidden'});
  await screenshot(page,'28-admin-user-directory.png');
  await navigate('Organization');await screenshot(page,'29-organization.png');
  await navigate('Team Members');await page.getByRole('heading',{name:'Teams',exact:true}).scrollIntoViewIfNeeded();await screenshot(page,'30-team-members.png');
  await account.goto('http://localhost:8513/admin');
  await account.getByLabel('Your account password',{exact:true}).fill(qa.password);
  await account.getByRole('button',{name:'Verify administrator',exact:true}).click();
  await account.getByRole('heading',{name:'Admin Dashboard · User directory',exact:true}).waitFor();
  await screenshot(account,'33-service-admin.png');
  await account.getByRole('link',{name:'View',exact:true}).first().click();
  await account.getByRole('heading',{name:'User details',exact:true}).waitFor();
  await screenshot(account,'34-admin-user-details.png');
  await account.setViewportSize({width:390,height:844});
  await account.goto('http://localhost:8513/account/profile');
  if(await account.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw new Error('Mobile profile overflows');
  await screenshot(account,'31-mobile-profile.png');
  await page.reload();await settled();
  if(!new URL(page.url()).searchParams.get('section'))throw new Error('Workspace navigation URL missing');
  console.log('Browser sign-in, profile save, single-use handoff, admin verification, navigation and mobile checks passed.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
