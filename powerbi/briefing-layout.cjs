/* Native PBIR layout for the executive briefing. No custom visuals or images. */
const fs=require('node:fs');
const path=require('node:path');
module.exports=({base,json,literal:L,color:C,field:F,project:P})=>{
 const root='NYC311.Report/definition';
 const schema='https://developer.microsoft.com/json-schemas/fabric/item/report/definition';
 const ink='#17343D', paper='#F5F3ED', white='#FFFEFA', teal='#087F86', amber='#AE681A', muted='#63737A', faint='#E4E6E0';
 let z=0;
 const metric=(n,label)=>P('Metrics',n,true,label);
 const column=(t,n,label)=>P(t,n,false,label);
 // Remove only these generated visual folders; never a working copy or PBIX.
 const generatedRoot=path.resolve(base,root,'pages');
 for(const page of ['weekly','investigate']){
  const visualRoot=path.resolve(generatedRoot,page,'visuals');
  if(!visualRoot.startsWith(generatedRoot+path.sep))throw new Error('Invalid generated output directory');
  fs.rmSync(visualRoot,{recursive:true,force:true});
 }
 function save(page,name,v){json(`${root}/pages/${page}/visuals/${name}/visual.json`,v);return v;}
 function frame(title='',fill=white){return {
  title:[{properties:{show:L(!!title),text:L(title),fontSize:L(12),fontColor:C(ink),fontFamily:L('Segoe UI Semibold'),bold:L(true)}}],
  background:[{properties:{show:L(!!fill),color:C(fill||paper),transparency:L(0)}}],
  border:[{properties:{show:L(false)}}],
  padding:[{properties:{top:L(10),bottom:L(8),left:L(12),right:L(12)}}]
 };}
 function visual(page,name,type,pos,title,roles,objects={},extra={}){
  if(type==='multiRowCard')objects={card:[{properties:{barShow:L(false),barWeight:L(0),cardPadding:L(0),outline:L('None'),outlineWeight:L(0)}}],...objects};
  return save(page,name,{$schema:`${schema}/visualContainer/2.0.0/schema.json`,name,position:{x:pos[0],y:pos[1],width:pos[2],height:pos[3],z:z++,tabOrder:z},visual:{visualType:type,visualContainerObjects:frame(title),objects,...(roles?{query:{queryState:Object.fromEntries(Object.entries(roles).map(([r,p])=>[r,{projections:p}]))}}:{})},...extra});
 }
 function text(page,name,pos,value,size=13,color=ink,bold=false,fill=null){
  const v=visual(page,name,'textbox',pos,'',null,{general:[{properties:{paragraphs:[{textRuns:[{value,textStyle:{fontFamily:bold?'Segoe UI Semibold':'Segoe UI',fontSize:size+'px',color,fontWeight:bold?'bold':'normal'}}]}]}}]});
  v.visual.visualContainerObjects=frame('',fill);v.visual.visualContainerObjects.padding=[{properties:{top:L(0),bottom:L(0),left:L(0),right:L(0)}}];
  return save(page,name,v);
 }
 function measureText(page,name,pos,measure,size=16,color=ink,fill=null){
  const v=visual(page,name,'multiRowCard',pos,'',{Values:[metric(measure)]},{dataLabels:[{properties:{fontSize:L(size),color:C(color),fontFamily:L('Segoe UI')}}],cardTitle:[{properties:{fontSize:L(size),color:C(color),fontFamily:L('Segoe UI')}}],categoryLabels:[{properties:{show:L(false)}}]});
  v.visual.visualContainerObjects=frame('',fill);v.visual.visualContainerObjects.padding=[{properties:{top:L(0),bottom:L(0),left:L(0),right:L(0)}}];
  return save(page,name,v);
 }
 function stat(page,name,x,y,w,measure,title,context,color=ink){
  const v=visual(page,name,'multiRowCard',[x,y,w,112],title,{Values:[metric(measure)]},{dataLabels:[{properties:{fontSize:L(28),color:C(color),fontFamily:L('Segoe UI Semibold')}}],categoryLabels:[{properties:{show:L(false)}}]});
  v.visual.visualContainerObjects.padding=[{properties:{top:L(4),bottom:L(0),left:L(14),right:L(10)}}];save(page,name,v);
  text(page,name+'_context',[x+14,y+86,w-24,24],context,11,muted);
 }
 function button(page,name,pos,label,action,destination){
  const v=visual(page,name,'actionButton',pos,'',null,{
   text:[{properties:{show:L(true)}},{selector:{id:'default'},properties:{text:L(label),fontSize:L(11),fontColor:C(white),horizontalAlignment:L('center')}}],
   icon:[{properties:{show:L(false)}},{selector:{id:'default'},properties:{placement:L('left')}}],
   fill:[{properties:{show:L(true)}},{selector:{id:'default'},properties:{fillColor:C(teal)}},{selector:{id:'hover'},properties:{fillColor:C(ink)}},{selector:{id:'disabled'},properties:{fillColor:C('#9CA7A6')}}],
   outline:[{properties:{show:L(false)}}],
   shape:[{properties:{tileShape:L('rectangleRounded'),roundEdge:{expr:{Literal:{Value:'4L'}}}}},{selector:{id:'default'},properties:{tileShape:L('rectangleRounded')}}]
  });
  v.visual.visualContainerObjects=frame('',null);
  v.visual.visualContainerObjects.visualLink=[{properties:{show:L(true),type:L(action),...(destination?{[action==='Drillthrough'?'drillthroughSection':'navigationSection']:L(destination)}:{}),tooltip:L(action==='Drillthrough'?'Select one ranked segment, then open its investigation.':'Return to the weekly briefing.'),...(action==='Drillthrough'?{disabledTooltip:L('Select a segment row first.')}:{})}}];
  v.visual.drillFilterOtherVisuals=true;v.howCreated='InsertVisualButton';save(page,name,v);
 }
 function measureFilter(name,measure,value=1){return {name,field:F('Metrics',measure,true),type:'Advanced',filter:{Version:2,From:[{Name:'m',Entity:'Metrics',Type:0}],Where:[{Condition:{Comparison:{ComparisonKind:0,Left:{Measure:{Expression:{SourceRef:{Source:'m'}},Property:measure}},Right:{Literal:{Value:value+'L'}}}}}]}};}
 function slicer(page,name,pos,table,field,label,date=false){
  const v=visual(page,name,'slicer',pos,label,{Values:[column(table,field)]},{data:[{properties:{mode:L(date?'Between':'Dropdown')}}],header:[{properties:{show:L(false)}}],items:[{properties:{fontColor:C(ink),textSize:L(11)}}]});
  v.visual.visualContainerObjects.padding=[{properties:{top:L(0),bottom:L(0),left:L(12),right:L(12)}}];save(page,name,v);
 }
 function page(name,title){
  const p={$schema:`${schema}/page/2.0.0/schema.json`,name,displayName:name==='weekly'?'Weekly operations':'Backlog investigation',displayOption:'FitToPage',height:960,width:1440,objects:{background:[{properties:{color:C(paper),transparency:L(0)}}]}};
  if(name==='investigate'){
   p.type='Drillthrough';p.filterConfig={filters:['Agency','Problem','Borough'].map(t=>({name:'drill_'+t.toLowerCase(),field:F(t,t.toLowerCase()),type:'Categorical',howCreated:'Drillthrough'}))};
   p.pageBinding={name:'segment_detail',type:'Drillthrough',acceptsFilterContext:'Default',parameters:['Agency','Problem','Borough'].map(t=>({name:t.toLowerCase(),boundFilter:'drill_'+t.toLowerCase(),fieldExpr:F(t,t.toLowerCase())}))};
  }
  json(`${root}/pages/${name}/page.json`,p);
  text(name,name+'_header_band',[0,0,1440,88],'',12,white,false,ink);
  text(name,name+'_eyebrow',[36,14,600,22],'NYC 311  /  SERVICE OPERATIONS BRIEF',12,'#BFD8D8',true);
  text(name,name+'_heading',[36,38,600,44],title,29,white,true);
  measureText(name,name+'_release',[650,16,754,30],'Release context',10,'#E1ECEB');
  measureText(name,name+'_coverage',[650,48,754,30],'Cohort coverage',10,'#E1ECEB');
  const filterY=name==='investigate'?216:242;
  slicer(name,name+'_date',[36,filterY,326,80],'Date','date_key','Activity period · event dates',true);
  slicer(name,name+'_agency',[378,filterY,192,80],'Agency','agency','Agency');
  slicer(name,name+'_problem',[586,filterY,458,80],'Problem','problem','Problem');
  slicer(name,name+'_borough',[1060,filterY,344,80],'Borough','borough','Borough');
 }
 page('weekly','Where should the next review start?');
 text('weekly','weekly_priority_panel',[36,106,1368,126],'',12,ink,false,'#EFE5D3');
 text('weekly','weekly_priority_label',[54,118,1000,22],'RECOMMENDED INVESTIGATION  /  OBSERVED BACKLOG',11,amber,true);
 measureText('weekly','weekly_priority_headline',[54,140,1064,60],'Priority headline',25,ink);
 measureText('weekly','weekly_priority_evidence',[54,205,1064,24],'Priority evidence',12,ink);
 measureText('weekly','weekly_priority_number',[1150,113,220,90],'Priority aged display',40,amber);
 text('weekly','weekly_priority_number_label',[1150,209,220,18],'OPEN 7+ DAYS',12,amber,true);
 stat('weekly','weekly_intake',36,332,330,'Intake','REQUESTS CREATED','Creation-date activity period',teal);
 stat('weekly','weekly_closures',382,332,330,'Recorded closures','RECORDED CLOSURES','Closure-date activity period',ink);
 stat('weekly','weekly_backlog',728,332,330,'Observed backlog','OPEN AT OBSERVATION','Fixed snapshot · activity dates do not apply',amber);
 stat('weekly','weekly_p90',1074,332,330,'P90 hours to recorded closure','P90 RECORDED CLOSURE','',ink);
 measureText('weekly','weekly_p90_context',[1088,418,306,24],'P90 context',10,muted);
 const trend=visual('weekly','weekly_flow','lineChart',[36,464,660,278],'Demand and closures · complete comparable weeks',{Category:[column('Date','week_start','Week starting')],Y:[metric('Complete week intake','Intake'),metric('Complete week closures','Recorded closures')]},{
  dataPoint:[{selector:{metadata:'Metrics.Complete week intake'},properties:{fill:C(teal)}},{selector:{metadata:'Metrics.Complete week closures'},properties:{fill:C(ink)}}],
  legend:[{properties:{show:L(true),fontSize:L(10),labelColor:C(muted)}}],
  categoryAxis:[{properties:{showAxisTitle:L(false),fontSize:L(10),labelColor:C(muted)}}],
  valueAxis:[{properties:{showAxisTitle:L(false),fontSize:L(10),labelColor:C(muted),gridlineColor:C(faint)}}]
 },{filterConfig:{filters:[measureFilter('complete_comparable_week','Comparable week')]}});
 trend.visual.query.sortDefinition={sort:[{field:F('Date','week_start'),direction:'Ascending'}]};save('weekly','weekly_flow',trend);
 measureText('weekly','weekly_trend_context',[48,746,636,42],'Trend context',11,muted);
 const rank=visual('weekly','weekly_segments','tableEx',[716,464,688,340],'Ranked by requests open 7+ days',{Values:[column('Agency','agency','Agency'),column('Problem','problem','Problem'),column('Borough','borough','Borough'),metric('Backlog 7d+','7d+ open'),metric('Observed backlog','All open')]},{
  grid:[{properties:{rowPadding:L(3),gridVertical:L(false),gridHorizontal:L(false)}}],
  columnHeaders:[{properties:{fontSize:L(11),fontColor:C(muted),backColor:C(white),wordWrap:L(false),autoSizeColumnWidth:L(false),columnAdjustment:L('fixedWidth')}}],
  values:[{properties:{fontSize:L(11),fontColor:C(ink),backColor:C(white),wordWrap:L(false)}},{selector:{metadata:'Metrics.Backlog 7d+'},properties:{fontColor:C(amber)}}],
  total:[{properties:{fontSize:L(11),fontColor:C(ink),backColor:C('#ECEEE8')}}],
  columnWidth:[['Agency.agency',70],['Problem.problem',190],['Borough.borough',190],['Metrics.Backlog 7d+',90],['Metrics.Observed backlog',90]].map(([ref,width])=>({selector:{metadata:ref},properties:{value:{expr:{Literal:{Value:width+'D'}}}}}))
 });rank.visual.query.sortDefinition={sort:[{field:F('Metrics','Backlog 7d+',true),direction:'Descending'}]};save('weekly','weekly_segments',rank);
 button('weekly','weekly_drill_button',[1134,812,270,44],'Investigate selected segment','Drillthrough','investigate');
 text('weekly','weekly_drill_hint',[728,816,390,38],'Select a row, then investigate. Right-click drill-through also works.',11,muted);
 text('weekly','weekly_target_panel',[36,806,660,84],'',12,ink,false,white);
 text('weekly','weekly_target_title',[50,816,630,22],'72-hour DEMO target · mature creation cohort',12,ink,true);
 measureText('weekly','weekly_target',[50,838,160,50],'Within demo target %',26,teal);
 measureText('weekly','weekly_target_evidence',[222,846,460,32],'Target evidence',11,muted);
 text('weekly','weekly_notes',[36,900,1368,42],'Fixed cohort, not citywide workload. One observed backlog snapshot; no backlog trend is inferred. Demo targets are illustrative. Recorded closure is not proof of fulfillment or staffing need.',12,muted);

 page('investigate','What should the analyst inspect?');
 measureText('investigate','investigate_selected',[36,104,1100,60],'Investigation headline',24,ink);
 button('investigate','investigate_back',[1184,108,220,44],'Back to weekly briefing','Back');
 text('investigate','investigate_action',[36,166,1368,42],'NEXT CHECK  /  Inspect oldest IDs for closure updates and routing. Recapture this cohort in one week to test whether aging changed; one snapshot cannot explain the cause.',15,ink);
 stat('investigate','investigate_open',36,310,330,'Observed backlog','OPEN AT OBSERVATION','All ages · fixed capture',teal);
 stat('investigate','investigate_aged',382,310,330,'Backlog 7d+','OPEN 7+ DAYS','At least 168 elapsed hours',amber);
 stat('investigate','investigate_30d',728,310,330,'Open 30d+','OPEN 30+ DAYS','At least 720 elapsed hours',amber);
 stat('investigate','investigate_oldest',1074,310,330,'Oldest open days','OLDEST OPEN REQUEST','Days at observation · no staffing inference',ink);
 const age=visual('investigate','investigate_age','clusteredBarChart',[36,438,590,198],'Aging distribution · click a bar to narrow the worklist',{Category:[column('Age Bucket','bucket','Age')],Y:[metric('Backlog by age','Open requests')]},{
  dataPoint:[{properties:{defaultColor:C(teal)}}],labels:[{properties:{show:L(true),fontSize:L(10),color:C(ink)}}],
  categoryAxis:[{properties:{showAxisTitle:L(false),fontSize:L(11),labelColor:C(muted)}}],valueAxis:[{properties:{showAxisTitle:L(false),fontSize:L(10),labelColor:C(muted),gridlineColor:C(faint)}}]
 });
 text('investigate','investigate_target_panel',[646,438,758,100],'',12,ink,false,white);
 text('investigate','investigate_target_title',[660,448,724,22],'72-hour DEMO target · mature creation cohort',12,ink,true);
 [['Within demo target %','Within target'],['Demo target met','Met'],['Demo target eligible','Eligible'],['Demo target misses','Misses']].forEach(([m,label],i)=>{
  measureText('investigate','investigate_target_'+i,[660+i*184,475,170,43],m,23,teal);
  text('investigate','investigate_target_label_'+i,[660+i*184,516,170,20],label,11,muted);
 });
 text('investigate','investigate_exclusions_panel',[646,548,758,88],'',12,ink,false,white);
 text('investigate','investigate_exclusions_title',[660,556,724,22],'Outside denominator · creation-period diagnostics',12,ink,true);
 [['Immature cases','Not yet mature'],['Missing demo target','No target'],['Invalid outcomes','Invalid'],['Unknown outcomes','Unknown']].forEach(([m,label],i)=>{
  measureText('investigate','investigate_exclusions_'+i,[660+i*184,581,170,35],m,19,muted);
  text('investigate','investigate_exclusions_label_'+i,[660+i*184,614,170,20],label,11,muted);
 });
 const work=visual('investigate','investigate_requests','tableEx',[36,650,1368,238],'Request worklist · within selected creation dates · oldest open first',{Values:[column('Cases','request_id','Request ID'),column('Cases','created_date','Created NYC'),column('Cases','status','Status'),metric('Open request age hours','Open age · hours'),column('Cases','closed_date','Recorded closure'),column('Cases','elapsed_hours','Closure hours'),column('Cases','target_hours','Demo hours'),metric('Request eligibility label','Eligibility')]},{
  grid:[{properties:{rowPadding:L(3),gridVertical:L(false),gridHorizontal:L(false)}}],columnHeaders:[{properties:{fontSize:L(11),fontColor:C(muted),backColor:C(white),wordWrap:L(false),autoSizeColumnWidth:L(false),columnAdjustment:L('fixedWidth')}}],values:[{properties:{fontSize:L(12),fontColor:C(ink),backColor:C(white),wordWrap:L(false)}}],total:[{properties:{totals:L(false)}}],
  columnWidth:[['Cases.request_id',140],['Cases.created_date',155],['Cases.status',150],['Metrics.Open request age hours',155],['Cases.closed_date',175],['Cases.elapsed_hours',140],['Cases.target_hours',125],['Metrics.Request eligibility label',275]].map(([ref,width])=>({selector:{metadata:ref},properties:{value:{expr:{Literal:{Value:width+'D'}}}}}))
 },{filterConfig:{filters:[measureFilter('detail_current_observation','Request detail visible')]}});
 work.visual.query.sortDefinition={sort:[{field:F('Metrics','Open request age hours',true),direction:'Descending'}]};save('investigate','investigate_requests',work);
 text('investigate','investigate_notes',[36,902,1368,42],'Aging cards use the fixed observation. Target diagnostics and request rows use the selected creation dates. Click an age bar to show open rows in that bucket; click again to clear. Requests are public records; no addresses or free text are included.',12,muted);
};
