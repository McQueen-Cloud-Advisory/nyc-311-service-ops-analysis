/* Generate readable PBIP/TMDL/PBIR from the checked-in export contract.
 * Run: node powerbi/build-project.cjs
 * Do not regenerate over unsaved Power BI Desktop edits.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const base = __dirname;
const contract = JSON.parse(fs.readFileSync(path.join(base, 'export-contract.json'), 'utf8'));
const modelDir = 'NYC311.SemanticModel';
const reportDir = 'NYC311.Report';
const definition = `${modelDir}/definition`;
const schema = 'https://developer.microsoft.com/json-schemas/fabric';
function write(file, text) { fs.mkdirSync(path.dirname(path.join(base,file)), {recursive:true}); fs.writeFileSync(path.join(base,file), text.replace(/\r\n/g,'\n'), 'utf8'); }
function json(file, value) { write(file, JSON.stringify(value,null,2)+'\n'); }
function id(value) { const h=crypto.createHash('sha256').update(value).digest('hex').slice(0,32); return `${h.slice(0,8)}-${h.slice(8,12)}-${h.slice(12,16)}-${h.slice(16,20)}-${h.slice(20)}`; }
function quote(value) { return `'${value.replaceAll("'", "''")}'`; }
// DAX reserves some ordinary words (including Cases). Always quote table names
// in expressions even when the TMDL object declaration does not need quoting.
function quoteDaxTables(formula) { return formula.replace(/"(?:[^"]|"")*"|'(?:[^']|'')*'|\[(?:[^\]]|\]\])*\]|\b(?:Cases|Backlog|Agency|Problem|Borough|Metrics)\b/g, token => /^["'\[]/.test(token) ? token : quote(token)); }
const mTypes={text:'type text',date:'type date',datetimezone:'type datetimezone',int64:'Int64.Type',number:'type number',logical:'type logical'};
const tTypes={text:'string',date:'dateTime',datetimezone:'dateTime',int64:'int64',number:'double',logical:'boolean'};
const asMTypes = (columns) => '{'+Object.entries(columns).map(([n,t])=>`{"${n}", ${mTypes[t]}}`).join(', ')+'}';

json('NYC311.pbip',{$schema:`${schema}/pbip/pbipProperties/1.0.0/schema.json`,version:'1.0',artifacts:[{report:{path:reportDir}}],settings:{enableAutoRecovery:true}});
json(`${modelDir}/definition.pbism`,{$schema:`${schema}/item/semanticModel/definitionProperties/1.0.0/schema.json`,version:'4.0',settings:{qnaEnabled:false}});
json(`${reportDir}/definition.pbir`,{$schema:`${schema}/item/report/definitionProperties/2.0.0/schema.json`,version:'4.0',datasetReference:{byPath:{path:`../${modelDir}`}}});
write(`${definition}/database.tmdl`, 'database\n\tcompatibilityLevel: 1604\n');
write(`${definition}/model.tmdl`, `model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\n\tannotation PBI_QueryOrder = ${JSON.stringify([...contract.tables.map(t=>t.model),'Age Bucket','Metrics'])}\n\tannotation __PBI_TimeIntelligenceEnabled = 0\n\n${[...contract.tables.map(t=>t.model),'Age Bucket','Metrics'].map(t=>`ref table ${quote(t)}`).join('\n')}\n`);
const parameters = {
 pMode: {value:'CSV', values:['CSV','BigQuery']},
 pExportRoot: {value:'SET_ABSOLUTE_PATH_TO_data/demo_exports'},
 pReleaseId: {value:contract.release_parameter},
 pSourceProject: {value:'SET_GCP_PROJECT_ID'},
 pBillingProject: {value:'SET_GCP_BILLING_PROJECT_ID'},
 pDataset: {value:'nyc311_reporting'}
};
let expressions=Object.entries(parameters).map(([n,p])=>`expression ${n} = ${JSON.stringify(p.value)} meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true${p.values?', List={'+p.values.map(v=>JSON.stringify(v)).join(', ')+'}, DefaultValue='+JSON.stringify(p.value):''}]\n\tlineageTag: ${id(n)}\n`).join('\n');
expressions += '\nexpression fnReadReporting =\n'+fs.readFileSync(path.join(base,'queries/ReadReporting.m'),'utf8').trim().split('\n').map(l=>'\t\t'+l).join('\n')+'\n\tlineageTag: '+id('fnReadReporting')+'\n';
write(`${definition}/expressions.tmdl`,expressions);

for (const table of contract.tables) {
 let content=`table ${quote(table.model)}\n\tlineageTag: ${id(table.model)}\n`;
 if(table.model==='Backlog') content+='\tisHidden\n';
 for(const [column,type] of Object.entries(table.columns)) {
  const hidden=column.endsWith('_key')||column==='release_id'||column==='snapshot_id'||column==='target_version'||column.startsWith('is_')||['target_numerator','target_denominator'].includes(column);
  content+=`\n\tcolumn ${quote(column)}\n\t\tdataType: ${tTypes[type]}\n\t\tsourceColumn: ${column}\n\t\tsummarizeBy: none\n\t\tlineageTag: ${id(table.model+'.'+column)}\n`;
  if(hidden&&!(table.model==='Date'&&column==='date_key')) content+='\t\tisHidden\n';
  if(type==='date') content+='\t\tformatString: yyyy-MM-dd\n\t\tannotation UnderlyingDateTimeDataType = Date\n';
  if(type==='datetimezone') content+='\t\tformatString: yyyy-MM-dd HH:mm:ss\n';
  if(type==='number') content+='\t\tformatString: 0.0\n';
  if(type==='int64') content+='\t\tformatString: #,0\n';
 }
 content+=`\n\tpartition ${quote(table.model)} = m\n\t\tmode: import\n\t\tsource =\n`;
 content+=`\t\t\t\tfnReadReporting("${table.source}", ${asMTypes(table.columns)})\n`;
 content+='\n\tannotation PBI_ResultType = Table\n';
 write(`${definition}/tables/${table.model}.tmdl`,content);
}

let relationships='';
for(const fact of ['Cases','Backlog']) for(const dim of ['Agency','Problem','Borough']) {
 const column=dim.toLowerCase()+'_key';
 relationships+=`relationship ${id(fact+'.'+dim)}\n\tfromColumn: ${quote(fact)}.${quote(column)}\n\ttoColumn: ${quote(dim)}.${quote(column)}\n\tcrossFilteringBehavior: oneDirection\n\n`;
}
relationships+=`relationship ${id('Cases.creation')}\n\tfromColumn: Cases.created_date\n\ttoColumn: 'Date'.date_key\n\nrelationship ${id('Cases.closure')}\n\tisActive: false\n\tfromColumn: Cases.closed_date\n\ttoColumn: 'Date'.date_key\n`;
write(`${definition}/relationships.tmdl`,relationships);
write(`${definition}/tables/Age Bucket.tmdl`, `table 'Age Bucket'\n\tlineageTag: ${id('Age Bucket')}\n\n\tcolumn bucket\n\t\tdataType: string\n\t\tsourceColumn: bucket\n\t\tsummarizeBy: none\n\t\tsortByColumn: sort_order\n\n\tcolumn sort_order\n\t\tdataType: int64\n\t\tsourceColumn: sort_order\n\t\tisHidden\n\t\tsummarizeBy: none\n\n\tpartition 'Age Bucket' = m\n\t\tmode: import\n\t\tsource = #table(type table [bucket = text, sort_order = Int64.Type], {{"Under 24h", 1}, {"24–72h", 2}, {"72–168h", 3}, {"168h+", 4}, {"Unknown age", 5}})\n`);
const measures = [
 ['Intake','COALESCE(COUNTROWS(FILTER(Cases, NOT ISBLANK(Cases[created_date]))), 0)','#,0','Creation-date period; requests with a known local creation date within the pinned cohort.'],
 ['Recorded closures',`COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_recorded_closure] = TRUE(), USERELATIONSHIP('Date'[date_key], Cases[closed_date])), 0)`,'#,0','Closure-date period; only requests created within the pinned cohort.'],
 ['Observed backlog',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nRETURN IF(NOT ISBLANK(Snapshot), COALESCE(CALCULATE(SUM(Backlog[open_count]), Backlog[snapshot_id] = Snapshot, Backlog[is_release_snapshot] = TRUE()), 0))`,'#,0','Selected release observation; independent of the activity date period.'],
 ['Backlog 7d+',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nRETURN IF(NOT ISBLANK(Snapshot), COALESCE(CALCULATE(SUM(Backlog[age_168h_plus_count]), Backlog[snapshot_id] = Snapshot, Backlog[is_release_snapshot] = TRUE()), 0))`,'#,0','Open for at least 168 elapsed hours at the selected observation.'],
 ['Demo target met','COALESCE(SUM(Cases[target_numerator]), 0)','#,0','Mature eligible cases recorded closed within the assigned demonstration target; creation-date period.'],
 ['Demo target eligible','COALESCE(SUM(Cases[target_denominator]), 0)','#,0','All mature eligible cases in the creation-date period, including overdue open and late closed misses.'],
 ['Within demo target %','DIVIDE([Demo target met], [Demo target eligible])','0.0%','Ratio of summed numerator to summed denominator. BLANK when no eligible mature cases.'],
 ['P90 eligible closures',`COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_p90_eligible] = TRUE(), USERELATIONSHIP('Date'[date_key], Cases[closed_date])), 0)`,'#,0','Eligible case rows in the selected closure-date period.'],
 ['P90 hours to recorded closure',`VAR Eligible = CALCULATETABLE(FILTER(Cases, Cases[is_p90_eligible] = TRUE() && NOT ISBLANK(Cases[elapsed_hours])), USERELATIONSHIP('Date'[date_key], Cases[closed_date]))\nRETURN IF(COUNTROWS(Eligible) > 0, PERCENTILEX.INC(Eligible, Cases[elapsed_hours], 0.9))`,'0.0','Continuous/interpolated percentile across eligible case rows, not an average of segment percentiles.'],
 ['Missing demo target','COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_missing_target] = TRUE()), 0)','#,0','Creation-date period. Missing-target diagnostic; not in the mature eligible denominator.'],
 ['Immature cases','COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_immature] = TRUE()), 0)','#,0','Creation-date period. Assigned threshold has not elapsed by the observation.'],
 ['Invalid outcomes','COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_invalid_outcome] = TRUE()), 0)','#,0','Creation-date period. Invalid chronology or inconsistent outcome.'],
 ['Unknown outcomes','COALESCE(CALCULATE(COUNTROWS(Cases), Cases[is_unknown_outcome] = TRUE()), 0)','#,0','Creation-date period. Status does not support a known open/closed outcome.'],
 ['Backlog by age',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nRETURN IF(NOT ISBLANK(Snapshot), CALCULATE(SWITCH(SELECTEDVALUE('Age Bucket'[bucket]), "Under 24h", SUM(Backlog[age_under_24h_count]), "24–72h", SUM(Backlog[age_24_to_72h_count]), "72–168h", SUM(Backlog[age_72_to_168h_count]), "168h+", SUM(Backlog[age_168h_plus_count]), "Unknown age", SUM(Backlog[age_unknown_count])), Backlog[snapshot_id] = Snapshot, Backlog[is_release_snapshot] = TRUE()))`,'#,0','Open requests by elapsed age at the single selected capture.'],
 ['Request detail visible',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nVAR IsOpen = SELECTEDVALUE(Cases[is_backlog]) = TRUE()\nVAR AgeOrder = SWITCH(SELECTEDVALUE(Cases[age_bucket]), "Under 24 hours", 1, "24 to under 72 hours", 2, "72 to under 168 hours", 3, "168 hours or more", 4, "Unknown age", 5)\nVAR AgeMatches = NOT ISFILTERED('Age Bucket') || (IsOpen && CONTAINS(VALUES('Age Bucket'[sort_order]), 'Age Bucket'[sort_order], AgeOrder))\nRETURN IF(SELECTEDVALUE(Cases[snapshot_id]) = Snapshot && AgeMatches && (IsOpen || SELECTEDVALUE(Cases[target_denominator]) = 1), 1, 0)`,'0','Detail rows are open or mature eligible; selecting an age bar narrows details to open requests in that bucket, while retaining creation-date filtering.'],
 ['Open request age hours','IF(SELECTEDVALUE(Cases[is_backlog]) = TRUE(), SELECTEDVALUE(Cases[age_hours]))','0.0','Elapsed age at observation for open requests only; closed request rows remain BLANK.'],
 ['Selected segment',`"Agency: " & IF(HASONEVALUE('Agency'[agency]), SELECTEDVALUE('Agency'[agency]), "All") & " | Problem: " & IF(HASONEVALUE('Problem'[problem]), SELECTEDVALUE('Problem'[problem]), "All") & " | Borough: " & IF(HASONEVALUE('Borough'[borough]), SELECTEDVALUE('Borough'[borough]), "All")`,null,'Visible segment context includes drill-through filters even when slicer captions say All.'],
 ['Release context',`"Release " & SELECTEDVALUE('Release'[release_id], "INVALID") & " | " & SELECTEDVALUE('Release'[source_kind], "UNKNOWN") & " | As of " & FORMAT(SELECTEDVALUE('Release'[observed_at]), "yyyy-MM-dd HH:mm") & " UTC"`,null,'Selected completed observation and provenance.'],
 ['Cohort coverage',`"Created " & FORMAT(SELECTEDVALUE('Release'[cohort_start]), "yyyy-MM-dd") & " through " & FORMAT(SELECTEDVALUE('Release'[cohort_end]) - 1, "yyyy-MM-dd") & " (NYC) | Captured " & FORMAT(SELECTEDVALUE('Release'[source_count]), "#,0") & " / " & FORMAT(SELECTEDVALUE('Release'[expected_count]), "#,0") & " requests"`,null,'Pinned creation cohort and complete-extract count; not citywide workload.'],
 ['Period context',`"Activity period: " & FORMAT(MIN('Date'[date_key]), "yyyy-MM-dd") & " to " & FORMAT(MAX('Date'[date_key]), "yyyy-MM-dd") & ". Intake/targets use creation; closures/p90 use closure; backlog uses the displayed observation."`,null,'Explicit date roles; backlog does not respond to the activity period.']
];
// Briefing helpers keep the governed base KPIs unchanged. Priority uses the
// single observed snapshot and ignores the activity date period, as backlog does.
const priorityRows = `VAR Segments = CALCULATETABLE(SUMMARIZE('Backlog', 'Agency'[agency], 'Problem'[problem], 'Borough'[borough], "__Aged", [Backlog 7d+], "__Open", [Observed backlog]), REMOVEFILTERS('Date'))\nVAR Ranked = TOPN(1, FILTER(Segments, [__Aged] > 0), [__Aged], DESC, [__Open], DESC, 'Agency'[agency], ASC, 'Problem'[problem], ASC, 'Borough'[borough], ASC)\n`;
measures.push(
 ['Priority segment',priorityRows+`RETURN IF(COUNTROWS(Ranked) > 0, MAXX(Ranked, 'Agency'[agency] & " / " & 'Problem'[problem] & " / " & 'Borough'[borough]))`,null,'Segment with most observed open requests aged at least seven days; deterministic ties use open count then agency/problem/borough.'],
 ['Priority aged count',priorityRows+`RETURN MAXX(Ranked, [__Aged])`,'#,0','Seven-day-plus open count of the recommended segment; BLANK when no aged backlog in the selected scope.'],
 ['Priority aged display',`IF(ISBLANK([Priority aged count]), "—", FORMAT([Priority aged count], "#,0"))`,null,'Presentation-only priority count; an em dash denotes no recommended aged segment, while the numeric measure remains BLANK.'],
 ['Priority open count',priorityRows+`RETURN MAXX(Ranked, [__Open])`,'#,0','All observed open requests in the recommended segment.'],
 ['Priority aged share','DIVIDE([Priority aged count], [Backlog 7d+])','0.0%','Recommended segment share of all aged backlog in the selected agency/problem/borough scope.'],
 ['Priority aged rate','DIVIDE([Priority aged count], [Priority open count])','0.0%','Share of the recommended segment open requests aged seven days or more.'],
 ['Priority headline',`IF(NOT ISBLANK([Priority segment]), "Review " & [Priority segment] & " first", "No requests aged 7+ days in this selection")`,null,'Filter-aware recommendation; this does not assert operational cause.'],
 ['Priority evidence',`IF(NOT ISBLANK([Priority aged count]), FORMAT([Priority aged count], "#,0") & " of " & FORMAT([Backlog 7d+], "#,0") & " requests in the filtered aged backlog (" & FORMAT([Priority aged share], "0.0%") & "). Start with the oldest IDs.", "Choose another segment or review the open-request worklist.")`,null,'Visible evidence behind the priority, always respecting the selected segment scope.'],
 ['Comparable week',`VAR WeekStart = SELECTEDVALUE('Date'[week_start])\nRETURN IF(NOT ISBLANK(WeekStart) && WeekStart >= SELECTEDVALUE('Release'[cohort_start]) && WeekStart + 7 <= SELECTEDVALUE('Release'[cohort_end]) && COUNTROWS(VALUES('Date'[date_key])) = 7, 1, 0)`,'0','Only full Monday-to-Sunday weeks inside the creation cohort and selected activity dates.'],
 ['Complete week intake','IF([Comparable week] = 1, [Intake])','#,0','Creation events within complete comparable weeks; out-of-cohort and partial selected weeks return BLANK.'],
 ['Complete week closures','IF([Comparable week] = 1, [Recorded closures])','#,0','Recorded closure events in the same complete weeks; limited to requests created in the pinned cohort.'],
 ['Complete week count',`COALESCE(COUNTROWS(FILTER(VALUES('Date'[week_start]), CALCULATE([Comparable week]) = 1)), 0)`,'0','Count of complete selected weeks eligible for the comparative trend.'],
 ['Trend context',`FORMAT([Complete week count], "0") & " full cohort weeks · partial weeks omitted."`,null,'Makes the comparable-week restriction explicit; intake uses creation dates and recorded closures use closure dates.'],
 ['Open 30d+',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nRETURN COALESCE(CALCULATE(COUNTROWS('Cases'), REMOVEFILTERS('Date'), 'Cases'[snapshot_id] = Snapshot, 'Cases'[is_backlog] = TRUE(), 'Cases'[age_hours] >= 720), 0)`,'#,0','Open at least thirty elapsed days at the observed snapshot; ignores activity date.'],
 ['Oldest open days',`VAR Snapshot = SELECTEDVALUE('Release'[snapshot_id])\nRETURN DIVIDE(CALCULATE(MAX('Cases'[age_hours]), REMOVEFILTERS('Date'), 'Cases'[snapshot_id] = Snapshot, 'Cases'[is_backlog] = TRUE()), 24)`,'0.0','Maximum open-request age in days at observation; BLANK if no open requests.'],
 ['Demo target misses','[Demo target eligible] - [Demo target met]','#,0','Eligible mature late-closed or overdue-open requests; creation-date period.'],
 ['P90 context',`"hours · " & FORMAT([P90 eligible closures], "#,0") & " eligible closures"`,null,'Eligible denominator displayed alongside the p90 KPI.'],
 ['Target evidence',`IF([Demo target eligible] > 0, FORMAT([Demo target met], "#,0") & " / " & FORMAT([Demo target eligible], "#,0") & " mature eligible · " & FORMAT([Demo target misses], "#,0") & " misses", "No mature eligible requests in the selected creation period")`,null,'Keeps numerator, denominator, and misses visible with the demo-target rate.'],
 ['Investigation headline',`IF(HASONEVALUE('Problem'[problem]) && HASONEVALUE('Borough'[borough]), SELECTEDVALUE('Borough'[borough]) & " / " & SELECTEDVALUE('Problem'[problem]), "Investigate the selected request scope")`,null,'Visible selected-segment heading, including drillthrough filters.'],
 ['Request eligibility label',`SWITCH(SELECTEDVALUE('Cases'[target_eligibility_reason]), "eligible_mature", "Mature · eligible", "immature", "Not yet mature", "missing_target", "Missing demo target", "invalid_outcome", "Invalid outcome", "unknown_outcome", "Unknown outcome")`,null,'Human-readable request-level eligibility.'],
 ['Visible worklist rows',`COALESCE(SUMX(VALUES('Cases'[request_id]), [Request detail visible]), 0)`,'#,0','Count of request worklist rows after activity-period and optional open-age selection.']
);
let measureText=`table Metrics\n\tlineageTag: ${id('Metrics')}\n\n\tcolumn placeholder\n\t\tdataType: int64\n\t\tsourceColumn: placeholder\n\t\tisHidden\n\t\tsummarizeBy: none\n\n\tpartition Metrics = m\n\t\tmode: import\n\t\tsource = #table(type table [placeholder = Int64.Type], {{1}})\n`;
for(const [name,formula,format,description] of measures) {
 measureText+=`\n\t/// ${description}\n\tmeasure ${quote(name)} =\n${quoteDaxTables(formula).split('\n').map(l=>'\t\t\t'+l).join('\n')}\n\t\tlineageTag: ${id('measure.'+name)}\n`;
 if(format) measureText+=`\t\tformatString: ${format}\n`;
}
write(`${definition}/tables/Metrics.tmdl`,measureText);

// PBIR uses native visuals only. No custom visuals, external images, or links.
const reportBase=`${reportDir}/definition`;
json(`${reportBase}/version.json`,{$schema:`${schema}/item/report/definition/versionMetadata/1.0.0/schema.json`,version:'2.0.0'});
json(`${reportBase}/report.json`,{$schema:`${schema}/item/report/definition/report/3.0.0/schema.json`,themeCollection:{baseTheme:{name:'CY24SU06',reportVersionAtImport:{visual:'2.0.0',page:'2.0.0',report:'3.0.0'},type:'SharedResources'}},settings:{useStylableVisualContainerHeader:true,exportDataMode:'AllowSummarized',defaultDrillFilterOtherVisuals:true}});
json(`${reportBase}/pages/pages.json`,{$schema:`${schema}/item/report/definition/pagesMetadata/1.0.0/schema.json`,pageOrder:['weekly','investigate'],activePageName:'weekly'});
function literal(v) { return {expr:{Literal:{Value:typeof v==='string'?"'"+v.replaceAll("'","''")+"'":typeof v==='boolean'?String(v):String(v)+'D'}}}; }
function color(hex) { return {solid:{color:literal(hex)}}; }
function field(table,column,measure=false) {return {[measure?'Measure':'Column']:{Expression:{SourceRef:{Entity:table}},Property:column}};}
function project(table,column,measure=false,displayName) { return {field:field(table,column,measure),queryRef:table+'.'+column,...(displayName?{displayName}:{})}; }
const metric=(name)=>project('Metrics',name,true);
const col=(table,name,label)=>project(table,name,false,label);
function formatting(title) {return {title:[{properties:{show:literal(true),text:literal(title),fontSize:literal(12),fontColor:color('#16324F'),bold:literal(true)}}],background:[{properties:{show:literal(true),color:color('#FFFFFF'),transparency:literal(0)}}],border:[{properties:{show:literal(true),color:color('#E1E7EC'),radius:literal(6)}}]};}
let z=0;
function visual(page,name,type,pos,title,roles,objects={},extra={}) {
 const v={$schema:`${schema}/item/report/definition/visualContainer/2.0.0/schema.json`,name,position:{x:pos[0],y:pos[1],width:pos[2],height:pos[3],z:z++,tabOrder:z},visual:{visualType:type,visualContainerObjects:formatting(title),objects,...(roles?{query:{queryState:Object.fromEntries(Object.entries(roles).map(([r,p])=>[r,{projections:p}]))}}:{})},...extra};
 json(`${reportBase}/pages/${page}/visuals/${name}/visual.json`,v);return v;
}
function textbox(page,name,pos,text,size=13,colorHex='#425466') {
 const v=visual(page,name,'textbox',pos,'',null,{general:[{properties:{paragraphs:[{textRuns:[{value:text,textStyle:{fontFamily:'Segoe UI',fontSize:size+'px',color:colorHex}}]}]}}]});
 v.visual.visualContainerObjects={title:[{properties:{show:literal(false)}}],background:[{properties:{show:literal(false)}}],border:[{properties:{show:literal(false)}}],padding:[{properties:{top:literal(0),bottom:literal(0),left:literal(0),right:literal(0)}}]};
 json(`${reportBase}/pages/${page}/visuals/${name}/visual.json`,v);return v;
}
function slicer(page,name,pos,table,column,label,date=false) {
 return visual(page,name,'slicer',pos,label,{Values:[col(table,column)]},{data:[{properties:{mode:literal(date?'Between':'Dropdown')}}],header:[{properties:{show:literal(false)}}]});
}
function card(page,name,pos,title,items) {
 return visual(page,name,'multiRowCard',pos,title,{Values:items.map(metric)},{dataLabels:[{properties:{fontSize:literal(22),color:color('#16324F')}}],categoryLabels:[{properties:{show:literal(true),fontSize:literal(11),color:color('#526575')}}]});
}
function page(name,displayName) {
 const p={$schema:`${schema}/item/report/definition/page/2.0.0/schema.json`,name,displayName,displayOption:'FitToPage',height:960,width:1440,objects:{background:[{properties:{color:color('#F3F6F8'),transparency:literal(0)}}]}};
 if(name==='investigate') {
  p.type='Drillthrough';
  p.filterConfig={filters:['Agency','Problem','Borough'].map(t=>({name:`drill_${t.toLowerCase()}`,field:field(t,t.toLowerCase()),type:'Categorical',howCreated:'Drillthrough'}))};
  p.pageBinding={name:'segment_detail',type:'Drillthrough',acceptsFilterContext:'Default',parameters:['Agency','Problem','Borough'].map(t=>({name:t.toLowerCase(),boundFilter:`drill_${t.toLowerCase()}`,fieldExpr:field(t,t.toLowerCase())}))};
 }
 json(`${reportBase}/pages/${name}/page.json`,p);
 textbox(name,name+'_heading',[28,12,620,56],displayName.toUpperCase()+'  |  NYC 311',25,'#16324F');
 const context=card(name,name+'_segment_context',[658,16,754,48],'',['Selected segment']);
 context.visual.objects={dataLabels:[{properties:{fontSize:literal(12),color:color('#16324F')}}],categoryLabels:[{properties:{show:literal(false)}}]};
 context.visual.visualContainerObjects={title:[{properties:{show:literal(false)}}],background:[{properties:{show:literal(false)}}],border:[{properties:{show:literal(false)}}],padding:[{properties:{top:literal(0),bottom:literal(0),left:literal(0),right:literal(0)}}]};
 json(`${reportBase}/pages/${name}/visuals/${name}_segment_context/visual.json`,context);
 const banner=card(name,name+'_release',[28,70,1384,66],'Observation and creation-cohort coverage',['Release context','Cohort coverage']);
 banner.visual.objects={dataLabels:[{properties:{fontSize:literal(12),color:color('#16324F')}}],categoryLabels:[{properties:{show:literal(false)}}]};
 json(`${reportBase}/pages/${name}/visuals/${name}_release/visual.json`,banner);
 slicer(name,name+'_date',[28,148,330,76],'Date','date_key','Activity date period',true);
 slicer(name,name+'_agency',[376,148,240,76],'Agency','agency','Agency');
 slicer(name,name+'_problem',[634,148,432,76],'Problem','problem','Problem');
 slicer(name,name+'_borough',[1084,148,328,76],'Borough','borough','Borough');
}
page('weekly','Weekly operations');
card('weekly','weekly_kpis',[28,240,1384,112],'Intake: creation date | Closures and p90: closure date | Backlog: observation',['Intake','Recorded closures','Observed backlog','P90 hours to recorded closure','P90 eligible closures']);
const demand=visual('weekly','weekly_flow','lineChart',[28,368,668,332],'Weekly intake and recorded closures · pinned creation cohort',{Category:[col('Date','week_start','Week starting')],Y:[metric('Intake'),metric('Recorded closures')]});
demand.visual.query.sortDefinition={sort:[{field:field('Date','week_start'),direction:'Ascending'}]};
json(`${reportBase}/pages/weekly/visuals/weekly_flow/visual.json`,demand);
const segments=visual('weekly','weekly_segments','tableEx',[716,368,696,468],'Segments to investigate · right-click a row to drill through',{Values:[col('Agency','agency','Agency'),col('Problem','problem','Problem'),col('Borough','borough','Borough'),{...metric('Observed backlog'),displayName:'Open'},{...metric('Backlog 7d+'),displayName:'Age 7d+'},{...metric('Within demo target %'),displayName:'Demo target %'}]},{grid:[{properties:{rowPadding:literal(8)}}],columnHeaders:[{properties:{fontSize:literal(11),wordWrap:literal(true)}}],values:[{properties:{fontSize:literal(11),wordWrap:literal(true)}}]});
segments.visual.query.sortDefinition={sort:[{field:field('Metrics','Backlog 7d+',true),direction:'Descending'}]};
json(`${reportBase}/pages/weekly/visuals/weekly_segments/visual.json`,segments);
card('weekly','weekly_target',[28,716,668,120],'Demo target · mature creation cohort',['Within demo target %','Demo target met','Demo target eligible']);
textbox('weekly','weekly_notes',[28,852,1384,88],'Read the date roles before comparing KPIs. The activity period filters intake and demo targets by creation date, and closures/p90 by recorded closure date. Backlog stays fixed at the displayed observation. Closures and backlog cover only the pinned creation cohort. Demo targets are illustrative, not NYC commitments. Agency-recorded closure does not establish fulfillment, handle time, or staffing need.',14);

page('investigate','Backlog investigation');
card('investigate','investigate_kpis',[28,240,1384,104],'Snapshot aging and demo-target evidence',['Observed backlog','Backlog 7d+','Demo target met','Demo target eligible','Within demo target %']);
visual('investigate','investigate_age','clusteredBarChart',[28,360,570,240],'Open requests by age · observation time',{Category:[col('Age Bucket','bucket','Age at observation')],Y:[metric('Backlog by age')]});
card('investigate','investigate_exclusions',[618,360,794,132],'Creation-period diagnostics · outside target denominator',['Missing demo target','Immature cases','Invalid outcomes','Unknown outcomes']);
textbox('investigate','investigate_guidance',[618,508,794,92],'Use the segment filters or drill through from Weekly operations. Compare the target numerator with its denominator before judging the rate. Inspect oldest open requests and the eligibility reason; investigate operational causes separately.',14);
const details=visual('investigate','investigate_requests','tableEx',[28,616,1384,238],'Eligible request details · current observation · creation-period filter',{Values:[col('Cases','request_id','Request ID'),col('Cases','created_date','Created NYC'),col('Cases','closed_date','Recorded closure NYC'),col('Cases','status','Status'),metric('Open request age hours'),col('Cases','target_hours','Demo target hours'),col('Cases','elapsed_hours','Elapsed closure hours'),col('Cases','target_eligibility_reason','Eligibility reason')]},{columnHeaders:[{properties:{fontSize:literal(11),wordWrap:literal(true)}}],values:[{properties:{fontSize:literal(11)}}]},{filterConfig:{filters:[{name:'detail_current_observation',field:field('Metrics','Request detail visible',true),type:'Advanced',filter:{Version:2,From:[{Name:'m',Entity:'Metrics',Type:0}],Where:[{Condition:{Comparison:{ComparisonKind:0,Left:{Measure:{Expression:{SourceRef:{Source:'m'}},Property:'Request detail visible'}},Right:{Literal:{Value:'1L'}}}}}]}}]}});
details.visual.query.sortDefinition={sort:[{field:field('Metrics','Open request age hours',true),direction:'Descending'}]};
json(`${reportBase}/pages/investigate/visuals/investigate_requests/visual.json`,details);
textbox('investigate','investigate_notes',[28,870,1384,62],'Backlog is one actual capture, not a sum across dates. Details show open or mature target-eligible requests from that same capture. To inspect a different capture, load its published release ID. Missing and invalid coverage remain visible. All thresholds are DEMO TARGETS.',14);

// The editorial briefing replaces the original visual layout, retaining the
// same page names and semantic contract for the cached reviewer workflow.
require('./briefing-layout.cjs')({base,json,literal,color,field,project});
console.log(`Generated NYC311.pbip, ${contract.tables.length+2} model tables, and 2 report pages. Desktop refresh and visual inspection are still required.`);
