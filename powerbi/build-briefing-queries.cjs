const fs=require('node:fs');
const path=require('node:path');
const row=(scenario)=>`ROW(
    "release_id", SELECTEDVALUE('Release'[release_id]),
    "scenario", "${scenario}",
    "priority_label", [Priority segment],
    "priority_aged_count", [Priority aged count],
    "priority_aged_display", [Priority aged display],
    "priority_open_count", [Priority open count],
    "priority_aged_share", [Priority aged share],
    "priority_within_segment_aged_rate", [Priority aged rate],
    "selected_aged_count", [Backlog 7d+],
    "selected_open_count", [Observed backlog],
    "snapshot_open_30d_plus", [Open 30d+],
    "oldest_open_age_days", [Oldest open days],
    "target_misses", [Demo target misses],
    "complete_week_count", [Complete week count],
    "first_complete_week", FORMAT(MINX(FILTER(VALUES('Date'[week_start]), CALCULATE([Comparable week]) = 1), 'Date'[week_start]), "yyyy-MM-dd"),
    "last_complete_week", FORMAT(MAXX(FILTER(VALUES('Date'[week_start]), CALCULATE([Comparable week]) = 1), 'Date'[week_start]), "yyyy-MM-dd"),
    "nov16_trend_intake", CALCULATE([Complete week intake], REMOVEFILTERS('Date'), TREATAS({DATE(2026,11,16)}, 'Date'[week_start])),
    "nov16_trend_recorded_closures", CALCULATE([Complete week closures], REMOVEFILTERS('Date'), TREATAS({DATE(2026,11,16)}, 'Date'[week_start])),
    "nov9_trend_intake", CALCULATE([Complete week intake], REMOVEFILTERS('Date'), TREATAS({DATE(2026,11,9)}, 'Date'[week_start])),
    "nov9_trend_recorded_closures", CALCULATE([Complete week closures], REMOVEFILTERS('Date'), TREATAS({DATE(2026,11,9)}, 'Date'[week_start])),
    "worklist_unfiltered_age_row_count", [Visible worklist rows],
    "worklist_age_7d_plus_row_count", CALCULATE([Visible worklist rows], TREATAS({"168h+"}, 'Age Bucket'[bucket]))
)`;
const segment=(borough)=>`,
    TREATAS({"DSNY"}, 'Agency'[agency]),
    TREATAS({"Dirty Condition"}, 'Problem'[problem]),
    TREATAS({"${borough}"}, 'Borough'[borough])`;
const queries=[
 ['A','Overall priority and complete-week policy','overall',''],
 ['B','Filtered Brooklyn segment','brooklyn_dirty',segment('BROOKLYN')],
 ['C','Filtered Queens segment','queens_dirty',segment('QUEENS')],
 ['D','Empty selection','empty_borough',`, TREATAS({"__NO_SUCH_BOROUGH__"}, 'Borough'[borough])`],
 ['E','Date-role separation with snapshot priority unchanged','activity_week_2026_11_09',`, FILTER(ALL('Date'), 'Date'[date_key] >= DATE(2026,11,9) && 'Date'[date_key] < DATE(2026,11,16))`]
];
const text='// Focused briefing checks. Compare with briefing-reference.json; no mutation.\n\n'+queries.map(([id,title,scenario,filters])=>`// ${id}. ${title}\nEVALUATE\n${filters?'CALCULATETABLE(\n'+row(scenario)+filters+'\n)':row(scenario)}`).join('\n\n')+'\n';
fs.writeFileSync(path.join(__dirname,'reconciliation-briefing.dax'),text,'utf8');
