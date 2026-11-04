import {createClient,getAccessToken} from '@base44/sdk';
export const base44=createClient({appId:'6aea0ba86746c1a3df4fc282',token:getAccessToken(),serverUrl:window.location.origin,appBaseUrl:window.location.origin,requiresAuth:false});
export function signIn(){base44.auth.redirectToLogin(window.location.origin+'/app.html');}
export function signOut(){base44.auth.logout();}
export async function command(action,data={}){try{const response=await base44.functions.invoke('command',{action,data});return response.data;}catch(cause){const error=new Error(cause?.response?.data?.error||cause?.data?.error||cause?.message||'The authenticated cloud service could not complete this request');error.status=cause?.status||cause?.response?.status||500;if(error.status===401)window.dispatchEvent(new Event('sentinal-session-expired'));throw error;}}
let batch=null;
async function workspace(){if(!batch){batch=command('workspace');setTimeout(()=>{batch=null;},100);}return batch;}
export async function api(path,options={}){const method=options.method||'GET',data=options.body?JSON.parse(options.body):{};
if(path==='/api/session')return command('session');if(path==='/api/logout'){signOut();return {ok:true};}
const simple={'/api/summary':'summary','/api/devices':'devices','/api/cameras':'cameras','/api/models':'models','/api/incidents':'incidents','/api/audit':'audit'};if(simple[path]&&method==='GET'){if(path==='/api/audit')return command('audit');return (await workspace())[simple[path]];}
if(path==='/api/settings')return command(method==='GET'?'settings':'retention',data);
if(path==='/api/users')return command(method==='GET'?'users':'member',data);
let match=path.match(/^\/api\/incidents\/([^/]+)\/(review|audit)$/);if(match)return command(match[2]==='audit'?'incident_audit':'review',{...data,incident_id:decodeURIComponent(match[1])});
match=path.match(/^\/api\/devices\/([^/]+)\/disable$/);if(match)return command('disable_device',{device_id:decodeURIComponent(match[1])});
throw new Error('This operation is unavailable in the metadata-only cloud command center.');}
