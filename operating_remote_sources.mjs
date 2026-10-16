// Bounded public-document acquisition on the connected Windows device.
// No credentials, browser profiles, proxy changes, or execution-policy changes.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
const project=path.dirname(fileURLToPath(import.meta.url));
const configPath=path.resolve(project,process.argv[2]??'configs/operating_remote_sources.json');
const config=JSON.parse(fs.readFileSync(configPath,'utf8'));
const root=path.join(project,config.output_directory);
fs.mkdirSync(root,{recursive:true});
const lockPath=path.join(root,'acquisition.lock');
const lock=fs.openSync(lockPath,'wx');
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
const save=(name,obj)=>fs.writeFileSync(path.join(root,name),JSON.stringify(obj,null,2)+'\n',{flag:'wx'});
let cursor=0;
const results=[];
async function worker(){
 while(cursor<config.requests.length){
  const item=config.requests[cursor++];
  const record={...item,request_started_at:new Date().toISOString(),transport:`Desktop Commander Remote / Windows Node ${process.version} fetch`,http_status:null};
  try{
   const response=await fetch(item.url,{headers:{'User-Agent':'stock_win public research (https://github.com/parameciumvance/stock_win)'},signal:AbortSignal.timeout(25000),redirect:'error'});
   record.http_status=response.status;
   record.final_url=response.url;
   record.headers=Object.fromEntries(response.headers);
   const chunks=[];let bytes=0;
   for await(const chunk of response.body){bytes+=chunk.length;if(bytes>32*1024*1024)throw Error('Response exceeds 32 MiB limit');chunks.push(chunk);}
   const body=Buffer.concat(chunks);
   fs.writeFileSync(path.join(root,item.filename),body,{flag:'wx'});
   record.sha256=digest(body);record.size_bytes=body.length;
  }catch(error){record.error={name:error.name,message:error.message,cause:error.cause?{code:error.cause.code,message:error.cause.message}:null};}
  record.observed_at=new Date().toISOString();
  save(item.filename+'.meta.json',record);results.push(record);
  console.log(JSON.stringify({filename:item.filename,status:record.http_status,bytes:record.size_bytes,error:record.error}));
 }
}
try{await Promise.all([worker(),worker()]);save('results.json',{recorded_at:new Date().toISOString(),workers:2,requests:results,config_sha256:digest(fs.readFileSync(configPath))});}
finally{fs.closeSync(lock);fs.unlinkSync(lockPath);}
