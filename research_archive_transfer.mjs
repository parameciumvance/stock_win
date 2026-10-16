// Read a packaged research archive back through a dedicated Windows backup.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const project=path.dirname(fileURLToPath(import.meta.url));
if(!process.argv[2])throw Error('Provide a project-relative package receipt');
const receipt=JSON.parse(fs.readFileSync(path.resolve(project,process.argv[2]),'utf8'));
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
const source=fs.readFileSync(path.resolve(project,receipt.archive));
if(digest(source)!==receipt.sha256)throw Error('Archive hash mismatch');
const folder=path.join(os.homedir(),'stock_win_research_backups');fs.mkdirSync(folder,{recursive:true});
const backup=path.join(folder,receipt.backup_label+'_'+receipt.sha256+'.zip');
if(!fs.existsSync(backup))fs.writeFileSync(backup,source,{flag:'wx'});
const returned=fs.readFileSync(backup);
if(digest(returned)!==receipt.sha256)throw Error('Backup hash mismatch');
const retrieved=path.resolve(project,receipt.retrieved);
if(fs.existsSync(retrieved)){
 if(digest(fs.readFileSync(retrieved))!==receipt.sha256)throw Error('Existing retrieval differs; not overwritten');
}else fs.writeFileSync(retrieved,returned,{flag:'wx'});
const result={sha256:receipt.sha256,backup_path:backup,retrieved_path:receipt.retrieved,roundtrip_verified:true,
 verified_at:new Date().toISOString(),transport:'Desktop Commander Remote / Windows Node file copy',storage:'Windows user backup and WSL retrieval; same computer'};
const target=path.resolve(project,receipt.transfer_receipt);
if(fs.existsSync(target)){
 if(JSON.parse(fs.readFileSync(target,'utf8')).sha256!==receipt.sha256)throw Error('Existing transfer receipt differs');
}else fs.writeFileSync(target,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(result));
