// Syntax-only check using Microsoft's parser. This does not evaluate M or read data.
// Tool install: npm install --prefix powerbi/.tools/pq-parser --ignore-scripts
//              --no-audit --no-fund @microsoft/powerquery-parser@5.0.0
const fs=require('node:fs');
const path=require('node:path');
const crypto=require('node:crypto');
const parser=require('./.tools/pq-parser/node_modules/@microsoft/powerquery-parser');
const base=__dirname;
const folder=path.join(base,'NYC311.SemanticModel','definition');
const queries=[];

function nextExpression(lines,start,minimumTabs) {
  const result=[];
  for(let i=start;i<lines.length;i++) {
    const line=lines[i];
    if(line.trim()==='') {result.push('');continue;}
    if((line.match(/^\t*/)||[''])[0].length<minimumTabs)break;
    result.push(line.slice(minimumTabs));
  }
  return result.join('\n').trim();
}
const expressions=fs.readFileSync(path.join(folder,'expressions.tmdl'),'utf8').split(/\r?\n/);
for(let i=0;i<expressions.length;i++) {
  const m=expressions[i].match(/^expression (.+?) =\s*(.*)$/);
  if(m)queries.push({name:m[1],source:m[2]||nextExpression(expressions,i+1,2)});
}
for(const file of fs.readdirSync(path.join(folder,'tables')).filter(x=>x.endsWith('.tmdl'))) {
  const lines=fs.readFileSync(path.join(folder,'tables',file),'utf8').split(/\r?\n/);
  for(let i=0;i<lines.length;i++) {
    const m=lines[i].match(/^\t\tsource =\s*(.*)$/);
    if(m)queries.push({name:file.replace('.tmdl','')+' partition',source:m[1]||nextExpression(lines,i+1,4)});
  }
}
(async()=>{
  const results=[];
  for(const query of queries) {
    const result=await parser.TaskUtils.tryLexParse(parser.DefaultSettings,query.source);
    if(parser.TaskUtils.isError(result))throw new Error(query.name+': '+(result.error?.message||JSON.stringify(result.error)));
    results.push({name:query.name,result:'passed',sha256:crypto.createHash('sha256').update(query.source).digest('hex')});
  }
  const output={checked_at_utc:new Date().toISOString(),outcome:'passed',parser:'@microsoft/powerquery-parser@5.0.0',node_version:process.version,expressions_checked:results.length,results,power_query_execution:'unverified',desktop_refresh:'unverified',note:'Syntax parsing does not resolve library functions, evaluate M, contact data sources, or execute DAX.'};
  fs.mkdirSync(path.join(base,'validation'),{recursive:true});
  fs.writeFileSync(path.join(base,'validation','m_validation.json'),JSON.stringify(output,null,2)+'\n','utf8');
  console.log(`PASS: ${results.length} M expressions parsed. Power Query execution remains unverified.`);
})().catch(error=>{console.error(error.message);process.exitCode=1;});
