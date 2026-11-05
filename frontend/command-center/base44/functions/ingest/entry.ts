import {createClientFromRequest} from 'npm:@base44/sdk@0.8.40';
import {applyIngest,boundedBody,Fault,transaction} from '../../shared/core.js';
export default async function(req:Request){
 const response=(value:unknown,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',...(status===429?{'Retry-After':'10'}:{})}});
 try{if(req.method!=='POST')throw new Fault('POST is required',405);if(Number(req.headers.get('content-length')||0)>131072)throw new Fault('Request too large',413);const bytes=await boundedBody(req,131072);if(bytes.length>131072)throw new Fault('Request too large',413);const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));const id=Deno.env.get('SENTINAL_STATE_ID');if(!id)throw new Fault('Cloud authority is unavailable',503);const client=createClientFromRequest(req).asServiceRole;return response(await transaction(client,id,state=>applyIngest(state,req.headers,bytes,value)));
 }catch(error){return response({error:error instanceof Fault?error.message:'The cloud service could not accept this event'},error instanceof Fault?error.status:400);}
}
