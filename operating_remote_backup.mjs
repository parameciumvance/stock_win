// Copy the bounded source archive to a dedicated Windows backup and read it back.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const project=path.dirname(fileURLToPath(import.meta.url));
const root=path.join(project,'inputs/operating_pilot_20261016');
const receipt=JSON.parse(fs.readFileSync(path.join(project,'deliverables/operating_remote_20261016/package.json'),'utf8'));
const hash=body=>crypto.createHash('sha256').update(body).digest('hex');
const source=fs.readFileSync(path.join(root,'remote_checkpoint.zip'));
if(hash(source)!==receipt.sha256)throw Error('Source archive differs from package receipt');
const folder=path.join(os.homedir(),'stock_win_research_backups');fs.mkdirSync(folder,{recursive:true});
const backup=path.join(folder,'operating_remote_20261016_'+receipt.sha256+'.zip');
if(!fs.existsSync(backup))fs.writeFileSync(backup,source,{flag:'wx'});
const returned=fs.readFileSync(backup);
if(hash(returned)!==receipt.sha256)throw Error('Windows backup hash mismatch');
const retrieved=path.join(root,'remote_checkpoint.retrieved.zip');
if(fs.existsSync(retrieved)){
 if(hash(fs.readFileSync(retrieved))!==receipt.sha256)throw Error('Existing retrieved archive differs; preserve it for review');
}else fs.writeFileSync(retrieved,returned,{flag:'wx'});
const result={sha256:receipt.sha256,backup_path:backup,retrieved_path:retrieved,roundtrip_verified:true,
 verified_at:new Date().toISOString(),transport:'Desktop Commander Remote / Windows Node file copy',
 storage:'Dedicated Windows user-profile directory; same computer, no off-device backup claim'};
const target=path.join(root,'remote_transfer_receipt.json');
if(fs.existsSync(target)){
 const old=JSON.parse(fs.readFileSync(target,'utf8'));
 if(old.sha256!==receipt.sha256)throw Error('Existing transfer receipt differs');
}else fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(result));
