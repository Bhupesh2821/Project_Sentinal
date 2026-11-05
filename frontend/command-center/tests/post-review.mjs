// Read only: verify actual human-review audit persisted after the hosted UI test.
import fs from 'node:fs';
import {createClient} from '../node_modules/@base44/sdk/dist/index.js';
import {chromium} from '../../../work/browser-tools/node_modules/playwright/index.mjs';
const origin='https://sentinal-command-center-df4fc282.base44.app';
const config=JSON.parse(fs.readFileSync('config/connected/base44-state.json','utf8'));
const token=JSON.parse(fs.readFileSync('config/connected/base44-app-auth.json','utf8')).token;
const incident_id=JSON.parse(fs.readFileSync('docs/evidence/v03-2026-11-03/base44-hosted-browser.json','utf8')).reviewed_incident_id;
const client=createClient({appId:config.app_id,token,serverUrl:origin,appBaseUrl:origin});
const report={test:'Read-only actual hosted human review and audit persistence',incident_id,checks:{},passed:false};
let browser;const check=(name,ok)=>{report.checks[name]=Boolean(ok);if(!ok)throw new Error(name);};
try{const call=async(action,data={})=>(await client.functions.invoke('command',{action,data})).data;
const audit=(await call('incident_audit',{incident_id})).items;
report.audit=audit.map(({action,timestamp,actor})=>({action,timestamp,actor}));
check('acknowledgment_and_dismissal_persisted_in_audit',audit.some(x=>x.action==='ACKNOWLEDGED')&&audit.some(x=>x.action==='DISMISSED'));
check('human_review_actors_and_actual_timestamps_present',audit.every(x=>Boolean(x.actor)&&Number.isFinite(Date.parse(x.timestamp))));
const incident=(await call('incidents')).items.find(x=>x.incident_id===incident_id);
check('dismissed_review_remains_version_three',incident.status==='DISMISSED'&&incident.version===3);
browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,downloadsPath:process.cwd()+'/work/tmp/base44-browser-downloads'});
const context=await browser.newContext({viewport:{width:1440,height:1100}});await context.addInitScript(value=>localStorage.setItem('base44_access_token',value),token);
const page=await context.newPage();await page.goto(origin+'/app.html#incidents');await page.locator(`tr[data-id="${incident_id}"]`).waitFor({state:'visible',timeout:45000});await page.locator(`tr[data-id="${incident_id}"]`).click();await page.waitForFunction(()=>{const text=document.querySelector('.audit-list')?.textContent||'';return text.includes('ACKNOWLEDGED')&&text.includes('DISMISSED');},null,{timeout:30000});
check('actual_dashboard_renders_both_review_audit_entries',true);await page.screenshot({path:'docs/evidence/v03-2026-11-03/base44-incidents-audit.png',fullPage:true});report.passed=true;
}catch(error){report.failure=error.message;}finally{client.cleanup();if(browser)await browser.close();fs.writeFileSync('docs/evidence/v03-2026-11-03/base44-post-review.json',JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;}
