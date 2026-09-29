"""App-wide collapsible BA II Plus-style financial calculator."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit.components.v1 as components


_CORE_PATH = Path(__file__).resolve().parent.parent / "assets" / "financial_calculator_core.js"
_KEYMAP_PATH = Path(__file__).resolve().parent.parent / "assets" / "financial_calculator_keymap.js"

_CSS = r"""
#sf-calc-fab,#sf-calc-drawer,#sf-calc-drawer *{box-sizing:border-box}
#sf-calc-fab{position:fixed;right:22px;bottom:154px;z-index:999995;width:48px;height:48px;
 border:0;border-radius:14px;background:linear-gradient(135deg,#0f766e,#1d4ed8);color:#fff;
 box-shadow:0 7px 22px rgba(15,118,110,.35);cursor:pointer;font-size:22px;display:flex;
 align-items:center;justify-content:center;transition:transform .16s,box-shadow .16s}
#sf-calc-fab:hover{transform:translateY(-2px);box-shadow:0 10px 28px rgba(29,78,216,.4)}
#sf-calc-fab:focus-visible{outline:3px solid rgba(245,158,11,.45);outline-offset:3px}
#sf-calc-fab[hidden]{display:none!important}
body.sf-calc-page-open [data-testid="stMain"],body.sf-calc-page-open .stMain,body.sf-calc-page-open section.main{
 width:calc(100% - var(--sf-calc-reserved,368px))!important;
 max-width:calc(100% - var(--sf-calc-reserved,368px))!important;
 margin-right:var(--sf-calc-reserved,368px)!important;
 transition:width .25s cubic-bezier(.4,0,.2,1),max-width .25s cubic-bezier(.4,0,.2,1),margin-right .25s cubic-bezier(.4,0,.2,1)}
#sf-calc-drawer{--c-bg:#eef2f3;--c-panel:#20252b;--c-key:#f7f7f5;--c-key-text:#171717;
 --c-muted:#667085;--c-line:#d5dce5;--c-accent:#d3a72c;position:fixed;right:14px;top:48px;
 z-index:999996;width:min(340px,calc(100vw - 28px));padding:0;border:0;
 border-radius:16px;background:transparent;box-shadow:none;
 transform:translateX(calc(100% + 30px));opacity:0;pointer-events:none;
 transition:transform .25s cubic-bezier(.4,0,.2,1),opacity .2s,width .25s;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#101828}
#sf-calc-drawer.sf-open{transform:translateX(0);opacity:1;pointer-events:auto}
#sf-calc-drawer.sf-large{width:min(430px,calc(100vw - 28px))}
#sf-calc-drawer.sf-dark{--c-bg:#111827;--c-panel:#0b0f14;--c-key:#303640;--c-key-text:#f8fafc;
 --c-muted:#aeb8c7;--c-line:#46505f;color:#f8fafc}
.sf-calc-head{height:44px;margin:0 auto 7px;max-width:470px;padding:5px 6px 5px 12px;border:1px solid rgba(148,163,184,.6);
 border-radius:12px;display:flex;align-items:center;gap:7px;background:rgba(248,250,252,.82);
 box-shadow:0 5px 16px rgba(15,23,42,.14);backdrop-filter:blur(7px);cursor:ns-resize;touch-action:none;user-select:none}
.sf-dark .sf-calc-head{background:rgba(15,23,42,.84)}
.sf-calc-title{flex:1;min-width:0}.sf-calc-title strong{display:block;font-size:14px;letter-spacing:.02em}
.sf-calc-title span{display:block;color:var(--c-muted);font-size:10px;margin-top:1px}
.sf-calc-tool{width:34px;height:34px;border:1px solid var(--c-line);border-radius:9px;background:transparent;
 color:inherit;cursor:pointer;font-size:15px}.sf-calc-tool:hover{background:rgba(100,116,139,.13)}
.sf-calc-scroll{max-height:calc(100vh - 66px);overflow:auto;padding:0 10px 10px;background:transparent}
.sf-calc-machine{max-width:470px;margin:0 auto;background:linear-gradient(100deg,#17191c 0%,#33363a 47%,#151719 100%);
 border:2px solid #090a0b;border-radius:28px 28px 20px 20px;padding:17px 15px 18px;
 box-shadow:inset 2px 0 0 rgba(255,255,255,.12),inset -2px 0 0 rgba(0,0,0,.5),0 10px 26px rgba(0,0,0,.32)}
.sf-calc-brand{align-items:flex-end;display:flex;justify-content:space-between;color:#e8e8e6;font-size:15px;
 font-weight:500;letter-spacing:.04em;margin:0 7px 10px;text-shadow:0 1px #000}
.sf-calc-brand strong{font-family:Georgia,serif;font-size:20px;font-weight:500;letter-spacing:.01em}
.sf-calc-brand em{font-size:15px;font-weight:400}.sf-calc-brand small{color:#c8cdd2;font-size:8px;
 font-weight:700;letter-spacing:.08em;text-transform:uppercase}
.sf-calc-screen-wrap{background:linear-gradient(#b9b9b5,#858783);border:1px solid #050505;border-radius:14px;
 box-shadow:inset 0 1px rgba(255,255,255,.65);margin-bottom:9px;padding:9px 10px 6px}
.sf-calc-screen{min-height:78px;background:#bfc8a2;border:3px solid #2b2e29;border-radius:7px;padding:7px 9px;
 color:#172012;font-family:"Courier New",monospace;box-shadow:inset 0 2px 7px rgba(0,0,0,.32);margin:0}
.sf-calc-model{text-align:center;color:#17191c;font-size:8px;font-weight:800;letter-spacing:.24em;margin-top:5px}
.sf-calc-indicators{height:14px;font-size:10px;font-weight:700;letter-spacing:.08em}
#sf-calc-display{font-family:"Lucida Console","Courier New",monospace;font-size:25px;font-weight:500;letter-spacing:1px;
 line-height:35px;text-align:right;text-shadow:1px 0 rgba(24,32,20,.45);white-space:nowrap;overflow:hidden;text-overflow:clip;font-variant-numeric:tabular-nums}
.sf-calc-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));column-gap:8px;row-gap:14px;padding:9px 2px 0}
.sf-calc-key{position:relative;min-width:0;height:38px;border:1px solid #0b0c0d;border-radius:10px;
 background:#34373b;color:#fff;font-size:11px;font-weight:800;cursor:pointer;
 box-shadow:inset 0 1px 0 rgba(255,255,255,.24),0 3px 0 #090a0b;
 padding:3px 2px;user-select:none;-webkit-tap-highlight-color:transparent}
.sf-calc-key:hover{filter:brightness(1.15)}.sf-calc-key:active{transform:translateY(2px);box-shadow:0 1px 0 #090a0b}
.sf-calc-key.sf-gold{background:#d7ad33;color:#171717;border-color:#f4d267;box-shadow:inset 0 1px #f9df86,0 3px 0 #765a0b}
.sf-calc-key.sf-darkkey,.sf-calc-key.sf-op{background:linear-gradient(#3d4145,#25282c);color:#fff}
.sf-calc-key.sf-fin{background:linear-gradient(#ececeb,#c8c9c8);color:#141414;border-color:#f7f7f5;box-shadow:inset 0 1px #fff,0 3px 0 #727574}
.sf-calc-key.sf-num{background:linear-gradient(#b9bab8,#929391);color:#111;border-color:#d9d9d7;box-shadow:inset 0 1px #e9e9e7,0 3px 0 #545655;font-size:13px}
.sf-calc-key.sf-spacer{visibility:hidden}
.sf-calc-key .alt{position:absolute;left:-2px;right:-2px;top:-12px;color:#f2d346;font-size:7.5px;
 font-weight:900;line-height:9px;letter-spacing:.01em;white-space:nowrap;pointer-events:none;text-shadow:0 1px 1px #000}
@media(max-width:650px){#sf-calc-drawer,#sf-calc-drawer.sf-large{right:8px;top:8px;width:min(340px,calc(100vw - 16px))}
 .sf-calc-head{margin-left:10px;margin-right:10px}.sf-calc-scroll{padding:0 10px 10px}.sf-calc-machine{padding:14px 10px}.sf-calc-key{height:42px}}
"""

_HTML = r"""
<div class="sf-calc-head">
  <div class="sf-calc-title"><strong>Financial Calculator</strong><span>Drag this bar up or down</span></div>
  <button class="sf-calc-tool" id="sf-calc-theme" title="Switch calculator theme" aria-label="Switch calculator theme">◐</button>
  <button class="sf-calc-tool" id="sf-calc-expand" title="Enlarge calculator" aria-label="Enlarge calculator">⛶</button>
  <button class="sf-calc-tool" id="sf-calc-close" title="Close calculator" aria-label="Close calculator">×</button>
</div>
<div class="sf-calc-scroll">
 <div class="sf-calc-machine">
  <div class="sf-calc-brand"><strong>BA II <em>Plus-style</em></strong><small>Financial practice</small></div>
  <div class="sf-calc-screen-wrap"><div class="sf-calc-screen" aria-live="polite"><div class="sf-calc-indicators" id="sf-calc-indicators"></div><div id="sf-calc-display">0.00</div></div><div class="sf-calc-model">BUSINESS ANALYST</div></div>
  <div class="sf-calc-grid" id="sf-calc-grid"></div>
 </div>
</div>
"""

_LOGIC = r"""
(function () {
  'use strict';
  var P = window.parent, doc = P.document, M = P.SFCalculatorMath, KM = P.SFCalculatorKeyMap;
  var root = doc.getElementById('sf-calc-drawer');
  if (!root || !M || !KM) return;
  var display = root.querySelector('#sf-calc-display');
  var indicators = root.querySelector('#sf-calc-indicators');
  var STORAGE = 'sf_financial_calculator_state_v1';
  var defaults = {input:'0',entering:false,error:'',acc:null,op:null,stack:[],aosTokens:[],second:false,cpt:false,inv:false,hyp:false,memoryMode:null,lastAnswer:0,
    tvm:{n:0,iy:0,pv:0,pmt:0,fv:0,py:1,cy:1,begin:false},mem:[0,0,0,0,0,0,0,0,0,0],
    cash:{cf0:0,groups:[]},bond:{sdt:1.0124,cpn:0,rdt:12.3129,rv:100,dayCount:'ACT',frequency:2,yld:0,pri:0,ai:0},
    amort:{p1:1,p2:1,bal:0,prn:0,int:0},data:{points:[],index:1,field:'x'},stat:{method:'1-V'},
    iconv:{nom:0,eff:0,cy:1},date:{dt1:1.0124,dt2:1.0125,dbd:0,method:'ACT'},
    profit:{cost:0,sell:0,margin:0},breakeven:{fixed:0,variable:0,price:0,quantity:0,profit:0},
    depr:{method:'SL',life:1,startMonth:1,cost:0,salvage:0,year:1,dep:0,rbv:0,rdv:0},delta:{old:0,newValue:0,pd:1,pct:0},
    format:{decimals:2,angle:'DEG',date:'US',separator:'US',method:'CHN'},npvRate:0,npvResult:0,irrResult:0,mode:'normal',field:'',cfIndex:0};
  function load(){try{var saved=JSON.parse(P.localStorage.getItem(STORAGE)||'null')||{};var state=Object.assign({},defaults,saved);['tvm','cash','bond','amort','data','stat','iconv','date','profit','breakeven','depr','delta','format'].forEach(function(k){state[k]=Object.assign({},defaults[k],saved[k]||{});});delete state.history;return state;}catch(e){return Object.assign({},defaults);}}
  var S=load();
  var lastDispatch='';
  function save(){try{P.localStorage.setItem(STORAGE,JSON.stringify(S));}catch(e){}}
  function num(){var n=Number(S.input);return Number.isFinite(n)?n:0;}
  function fmt(value){if(!Number.isFinite(Number(value)))return 'Error';var n=Number(value),dec=Math.max(0,Math.min(9,Number(S.format.decimals)));if((Math.abs(n)>=1e10)||(Math.abs(n)>0&&Math.abs(n)<Math.pow(10,-Math.max(1,dec))))return n.toExponential(Math.min(8,Math.max(2,dec)));var options=dec===9?{maximumSignificantDigits:10}:{minimumFractionDigits:dec,maximumFractionDigits:dec};var out=n.toLocaleString(S.format.separator==='EUR'?'de-DE':'en-US',options);return out.length>13?n.toExponential(6):out;}
  function setValue(value){S.input=String(value);S.entering=false;S.lastAnswer=Number(value);display.textContent=fmt(value);}
  function addHistory(){save();}
  function annunciators(extra){return [(S.second?'2nd':''),(S.inv?'INV':''),(S.hyp?'HYP':''),(S.cpt?'COMPUTE':''),(extra||''),(S.tvm.begin?'BGN':''),(S.format.angle==='RAD'?'RAD':'')].filter(Boolean).join('   ');}
  function entryFmt(){var out=String(S.input).slice(0,12);if(S.format.separator==='EUR')out=out.replace('.',',');return out;}
  var worksheetFields={bond:['sdt','cpn','rdt','rv','dayCount','frequency','yld','pri','ai'],amort:['p1','p2','bal','prn','int'],
    stat:['method','n','meanX','sampleX','populationX','sumX','sumX2','meanY','sampleY','a','b','r'],iconv:['nom','eff','cy'],
    date:['dt1','dt2','dbd','method'],profit:['cost','sell','margin'],breakeven:['fixed','variable','price','quantity','profit'],
    depr:['method','life','startMonth','cost','salvage','year','dep','rbv','rdv'],delta:['old','newValue','pd','pct'],
    format:['decimals','angle','date','separator','method']};
  var fieldLabels={sdt:'SDT',cpn:'CPN',rdt:'RDT',rv:'RV',dayCount:'ACT/360',frequency:'2/Y',yld:'YLD',pri:'PRI',ai:'AI',
    p1:'P1',p2:'P2',bal:'BAL',prn:'PRN',int:'INT',method:'METHOD',meanX:'x̄',sampleX:'Sx',populationX:'σx',sumX:'Σx',sumX2:'Σx²',meanY:'ȳ',sampleY:'Sy',
    nom:'NOM',eff:'EFF',cy:'C/Y',dt1:'DT1',dt2:'DT2',dbd:'DBD',cost:'CST',sell:'SEL',margin:'MAR',fixed:'FC',variable:'VC',price:'P',quantity:'Q',profit:'PFT',
    life:'LIF',startMonth:'M01',salvage:'SAL',year:'YR',dep:'DEP',rbv:'RBV',rdv:'RDV',old:'OLD',newValue:'NEW',pd:'#PD',pct:'%CH',decimals:'DEC',angle:'DEG/RAD',date:'US/EUR',separator:'SEP'};
  function modeLabel(){if(S.mode==='cf'){if(S.cfIndex===0)return 'CF0';return S.field==='freq'?'F'+String(S.cfIndex).padStart(2,'0'):'C'+String(S.cfIndex).padStart(2,'0');}if(S.mode==='data')return (S.field==='y'?'Y':'X')+String(S.data.index).padStart(2,'0');if(S.mode==='npv')return S.field==='result'?'NPV':'I';if(S.mode==='irr')return 'IRR';if(S.mode==='py')return S.field==='cy'?'C/Y':'P/Y';if(S.mode==='bgn')return S.tvm.begin?'BGN':'END';if(S.mode==='mem')return 'M'+S.wsIndex;if(S.mode==='reset')return 'RST ?';return fieldLabels[S.field]||String(S.field||'').toUpperCase();}
  function statsResult(){return M.statistics(S.data.points,S.stat.method==='1-V');}
  function currentWorksheetValue(){
    if(S.mode==='cf'){if(S.cfIndex===0)return S.cash.cf0;var g=S.cash.groups[S.cfIndex-1]||{value:0,frequency:1};return S.field==='freq'?g.frequency:g.value;}
    if(S.mode==='data'){var point=S.data.points[S.data.index-1]||{x:0,y:1,frequency:1};return S.field==='y'?point.y:point.x;}
    if(S.mode==='npv')return S.field==='result'?(S.npvResult||0):(S.npvRate||0);
    if(S.mode==='irr')return S.irrResult||0;if(S.mode==='py')return S.field==='cy'?(S.tvm.cy||S.tvm.py):S.tvm.py;if(S.mode==='bgn')return S.tvm.begin?'BGN':'END';
    if(S.mode==='mem')return S.mem[S.wsIndex]||0;if(S.mode==='reset')return '';
    if(S.mode==='stat'){if(S.field==='method')return S.stat.method;var sr=statsResult();return sr[S.field];}
    if(S.mode==='amort'&&['bal','prn','int'].indexOf(S.field)>=0){var ar=M.amortization(S.tvm,S.amort.p1,S.amort.p2);S.amort.bal=ar.balance;S.amort.prn=ar.principal;S.amort.int=ar.interest;}
    if(S.mode==='depr'&&['dep','rbv','rdv'].indexOf(S.field)>=0){var dr=M.depreciation(S.depr.method,S.depr.cost,S.depr.salvage,S.depr.life,S.depr.year,200);S.depr.dep=dr.depreciation;S.depr.rbv=dr.remainingBookValue;S.depr.rdv=dr.remainingDepreciableValue;}
    var obj=S[S.mode];return obj&&obj[S.field]!==undefined?obj[S.field]:num();
  }
  function showWorksheet(){var label=modeLabel(),value;try{value=S.entering?num():currentWorksheetValue();}catch(e){value='Error';}display.textContent=S.entering?label+' = '+entryFmt():(typeof value==='string'&&value===label)?label:label+(value===''?'':(' = '+(typeof value==='string'?value:fmt(value))));indicators.textContent=annunciators(S.entering?'ENTER':'');}
  function show(){if(S.error){display.textContent=S.error;indicators.textContent='';return;}if(S.mode!=='normal'){showWorksheet();return;}display.textContent=S.entering?entryFmt():fmt(num());indicators.textContent=annunciators();}
  function ensureGroup(index){while(S.cash.groups.length<index)S.cash.groups.push({value:0,frequency:1});return S.cash.groups[index-1];}
  function storeWorksheet(){var value=num();if(S.mode==='cf'){if(S.cfIndex===0)S.cash.cf0=value;else{var g=ensureGroup(S.cfIndex);if(S.field==='freq')g.frequency=Math.max(1,Math.floor(value));else g.value=value;}}
    else if(S.mode==='data'){while(S.data.points.length<S.data.index)S.data.points.push({x:0,y:1,frequency:1});S.data.points[S.data.index-1][S.field]=value;}
    else if(S.mode==='npv'&&S.field!=='result')S.npvRate=value;else if(S.mode==='py'){value=Math.max(1,value);if(S.field==='cy')S.tvm.cy=value;else{S.tvm.py=value;S.tvm.cy=value;}}
    else if(S.mode==='mem')S.mem[S.wsIndex]=value;else if(S[S.mode]&&typeof S[S.mode][S.field]!=='string')S[S.mode][S.field]=value;
    S.entering=false;addHistory();showWorksheet();}
  function digit(key){if(S.memoryMode){var index=Number(key);if(S.memoryMode==='sto'){S.mem[index]=num();addHistory();}else{setValue(S.mem[index]||0);addHistory();}S.memoryMode=null;S.entering=false;show();return;}if(!S.entering){S.input=key==='.'?'0.':key;S.entering=true;}else if(key==='.'&&!S.input.includes('.'))S.input+='.';else if(key!=='.'&&S.input.replace(/[-.]/g,'').length<10)S.input+=key;show();}
  function calculate(a,op,b){if(op==='+')return a+b;if(op==='-')return a-b;if(op==='×')return a*b;if(op==='÷'){if(b===0)throw Error();return a/b;}if(op==='yˣ')return Math.pow(a,b);if(op==='nCr')return M.combinations(a,b);if(op==='nPr')return M.permutations(a,b);return b;}
  function operation(op){try{var v=num();if(S.format.method==='AOS'){S.aosTokens=S.aosTokens||[];if(S.entering||!S.aosTokens.length)S.aosTokens.push(v);if(typeof S.aosTokens[S.aosTokens.length-1]==='string'&&S.aosTokens[S.aosTokens.length-1]!==')')S.aosTokens[S.aosTokens.length-1]=op;else S.aosTokens.push(op);S.entering=false;addHistory();show();return;}if(S.op&&S.acc!==null&&S.entering)v=calculate(S.acc,S.op,v);S.acc=v;S.op=op;S.input=String(v);S.entering=false;addHistory();}catch(e){error();}show();}
  function equals(){try{if(S.format.method==='AOS'&&S.aosTokens&&S.aosTokens.length){var tokens=S.aosTokens.slice();if(S.entering)tokens.push(num());var aosResult=M.evaluateExpression(tokens);S.aosTokens=[];setValue(aosResult);}else if(S.op&&S.acc!==null){var result=calculate(S.acc,S.op,num());setValue(result);}S.op=null;S.acc=null;addHistory();}catch(e){error();}show();}
  function leftParen(){if(S.format.method==='AOS'){S.aosTokens=S.aosTokens||[];S.aosTokens.push('(');S.input='0';S.entering=false;show();save();return;}S.stack=S.stack||[];S.stack.push({acc:S.acc,op:S.op});S.acc=null;S.op=null;S.input='0';S.entering=false;addHistory();show();}
  function rightParen(){if(S.format.method==='AOS'){if(S.entering)S.aosTokens.push(num());S.aosTokens.push(')');S.entering=false;show();save();return;}if(!S.stack||!S.stack.length)return;try{var result=num();if(S.op&&S.acc!==null)result=calculate(S.acc,S.op,result);var outer=S.stack.pop();S.acc=outer.acc;S.op=outer.op;S.input=String(result);S.entering=!!S.op;addHistory();show();}catch(e){error();}}
  function unary(key){try{var v=num(),r=v;if(key==='%')r=M.percentOperand(S.acc,S.op,v);if(key==='√x')r=Math.sqrt(v);if(key==='x²')r=v*v;if(key==='1/x')r=1/v;if(key==='LN')r=Math.log(v);if(key==='eˣ')r=Math.exp(v);if(key==='ROUND')r=Number(v.toFixed(Math.min(8,Number(S.format.decimals)||0)));if(key==='SIN'||key==='COS'||key==='TAN'){var angle=S.format.angle==='RAD'?v:v*Math.PI/180;if(S.hyp){r=key==='SIN'?Math.sinh(v):key==='COS'?Math.cosh(v):Math.tanh(v);}else if(S.inv){r=key==='SIN'?Math.asin(v):key==='COS'?Math.acos(v):Math.atan(v);if(S.format.angle!=='RAD')r=r*180/Math.PI;}else r=key==='SIN'?Math.sin(angle):key==='COS'?Math.cos(angle):Math.tan(angle);S.inv=false;S.hyp=false;}setValue(r);addHistory();}catch(e){error();}show();}
  function error(){S.input='0';S.entering=false;S.error='Error 1';show();save();}
  function clearEntry(){S.error='';if(S.entering){S.input='0';S.entering=false;}else{S.input='0';S.acc=null;S.op=null;S.aosTokens=[];}show();}
  function clearTvm(){S.tvm.n=0;S.tvm.iy=0;S.tvm.pv=0;S.tvm.pmt=0;S.tvm.fv=0;S.mode='normal';addHistory('CLR TVM');show();}
  function clearWork(){S.cash={cf0:0,groups:[]};S.npvRate=0;S.npvResult=0;S.irrResult=0;S.mode='cf';S.cfIndex=0;S.field='value';addHistory();showWorksheet();}
  function activateWorksheet(mode,field){S.second=false;S.cpt=false;S.mode=mode;S.field=field||(worksheetFields[mode]||[''])[0];S.entering=false;if(mode==='data'){S.data.index=Math.max(1,S.data.index||1);S.field='x';}if(mode==='mem')S.wsIndex=0;showWorksheet();save();}
  function clearCurrentWorksheet(){var mode=S.mode;if(mode==='cf'||mode==='npv'||mode==='irr'){clearWork();return;}if(mode==='normal'){show();return;}if(mode==='data'||mode==='stat'){S.data={points:[],index:1,field:'x'};S.stat={method:'1-V'};activateWorksheet(mode,mode==='data'?'x':'method');return;}if(defaults[mode]&&typeof defaults[mode]==='object')S[mode]=JSON.parse(JSON.stringify(defaults[mode]));showWorksheet();save();}
  function baDateToDate(value){var fixed=Math.abs(Number(value)||0).toFixed(4).split('.'),month=Number(fixed[0]),tail=(fixed[1]||'0000').padEnd(4,'0'),day=Number(tail.slice(0,2)),yy=Number(tail.slice(2,4)),year=yy<70?2000+yy:1900+yy;return new Date(Date.UTC(year,month-1,day));}
  function dateToBa(date){var mm=date.getUTCMonth()+1,dd=String(date.getUTCDate()).padStart(2,'0'),yy=String(date.getUTCFullYear()).slice(-2);return Number(mm+'.'+dd+yy);}
  function computed(value){if(!Number.isFinite(Number(value)))throw Error();S.lastAnswer=Number(value);S.input=String(value);S.entering=false;S.cpt=false;display.textContent=modeLabel()+' = '+fmt(value);indicators.textContent=annunciators('=');save();}
  function computeWorksheet(){try{var value;
    if(S.mode==='npv'&&S.field==='result'){value=M.npv(S.npvRate||0,S.cash.cf0,S.cash.groups);S.npvResult=value;}
    else if(S.mode==='irr'){value=M.irr(S.cash.cf0,S.cash.groups);S.irrResult=value;}
    else if(S.mode==='bond'){var years=Math.abs(M.daysBetween(baDateToDate(S.bond.sdt),baDateToDate(S.bond.rdt),'ACT'))/365;if(S.field==='pri'){value=M.bondPrice(S.bond.rv,S.bond.cpn,S.bond.yld,years,S.bond.frequency);S.bond.pri=value;}else if(S.field==='yld'){value=M.bondYield(S.bond.pri,S.bond.rv,S.bond.cpn,years,S.bond.frequency);S.bond.yld=value;}else return;}
    else if(S.mode==='amort'){var ar=M.amortization(S.tvm,S.amort.p1,S.amort.p2);S.amort.bal=ar.balance;S.amort.prn=ar.principal;S.amort.int=ar.interest;value=S.amort[S.field];}
    else if(S.mode==='iconv'){if(S.field==='eff'){value=M.nominalToEffective(S.iconv.nom,S.iconv.cy);S.iconv.eff=value;}else if(S.field==='nom'){value=M.effectiveToNominal(S.iconv.eff,S.iconv.cy);S.iconv.nom=value;}else return;}
    else if(S.mode==='date'){if(S.field==='dbd'){value=M.daysBetween(baDateToDate(S.date.dt1),baDateToDate(S.date.dt2),S.date.method);S.date.dbd=value;}else if(S.field==='dt2'){var d=baDateToDate(S.date.dt1);d.setUTCDate(d.getUTCDate()+Number(S.date.dbd));value=dateToBa(d);S.date.dt2=value;}else return;}
    else if(S.mode==='profit'){value=M.profitMargin(S.field,S.profit);S.profit[S.field]=value;}
    else if(S.mode==='breakeven'){value=M.breakEven(S.field,S.breakeven);S.breakeven[S.field]=value;}
    else if(S.mode==='depr'){var dr=M.depreciation(S.depr.method,S.depr.cost,S.depr.salvage,S.depr.life,S.depr.year,200);S.depr.dep=dr.depreciation;S.depr.rbv=dr.remainingBookValue;S.depr.rdv=dr.remainingDepreciableValue;value=S.depr[S.field];}
    else if(S.mode==='delta'&&S.field==='pct'){value=M.percentChange(S.delta.old,S.delta.newValue,S.delta.pd);S.delta.pct=value;}
    else return;computed(value);
  }catch(e){error();}}
  function setWorksheetOption(){if(S.mode==='bgn'){S.tvm.begin=!S.tvm.begin;}
    else if(S.mode==='bond'&&S.field==='dayCount')S.bond.dayCount=S.bond.dayCount==='ACT'?'360':'ACT';
    else if(S.mode==='bond'&&S.field==='frequency')S.bond.frequency=S.bond.frequency===2?1:2;
    else if(S.mode==='stat'&&S.field==='method')S.stat.method=S.stat.method==='1-V'?'LIN':'1-V';
    else if(S.mode==='date'&&S.field==='method')S.date.method=S.date.method==='ACT'?'360':'ACT';
    else if(S.mode==='depr'&&S.field==='method'){var methods=['SL','SYD','DB'];S.depr.method=methods[(methods.indexOf(S.depr.method)+1)%methods.length];}
    else if(S.mode==='format'){if(S.field==='angle')S.format.angle=S.format.angle==='DEG'?'RAD':'DEG';else if(S.field==='date')S.format.date=S.format.date==='US'?'EUR':'US';else if(S.field==='separator')S.format.separator=S.format.separator==='US'?'EUR':'US';else if(S.field==='method')S.format.method=S.format.method==='CHN'?'AOS':'CHN';}
    showWorksheet();save();}
  function tvmKey(key){if(S.second){S.second=false;if(key==='iy'){S.mode='py';S.field='py';showWorksheet();return;}if(key==='pmt'){S.mode='bgn';showWorksheet();return;}if(key==='fv'){clearTvm();return;}}
    if(S.cpt){try{var result=M.solveTvm(key,S.tvm);S.tvm[key]=result;S.cpt=false;setValue(result);addHistory('CPT '+key.toUpperCase(),result);}catch(e){S.cpt=false;error();}show();return;}
    S.tvm[key]=num();S.entering=false;addHistory(key.toUpperCase(),S.tvm[key]);display.textContent=key.toUpperCase()+' = '+fmt(S.tvm[key]);save();}
  function arrows(direction){if(S.mode==='cf'){if(direction>0){if(S.cfIndex===0){S.cfIndex=1;S.field='value';}else if(S.field==='value')S.field='freq';else{S.cfIndex+=1;S.field='value';ensureGroup(S.cfIndex);}}else{if(S.cfIndex===0)return;if(S.field==='freq')S.field='value';else if(S.cfIndex===1)S.cfIndex=0;else{S.cfIndex-=1;S.field='freq';}}}
    else if(S.mode==='data'){if(direction>0){if(S.field==='x')S.field='y';else{S.data.index+=1;S.field='x';}}else{if(S.field==='y')S.field='x';else if(S.data.index>1){S.data.index-=1;S.field='y';}}}
    else if(S.mode==='npv')S.field=S.field==='result'?'rate':'result';else if(S.mode==='py')S.field=S.field==='cy'?'py':'cy';
    else if(worksheetFields[S.mode]){var fields=worksheetFields[S.mode],at=Math.max(0,fields.indexOf(S.field));S.field=fields[Math.max(0,Math.min(fields.length-1,at+direction))];}
    else if(S.mode==='mem')S.wsIndex=Math.max(0,Math.min(9,S.wsIndex+direction));showWorksheet();}
  function deleteWorksheetItem(){if(S.mode==='cf'&&S.cfIndex>0){S.cash.groups.splice(S.cfIndex-1,1);S.cfIndex=Math.max(0,Math.min(S.cfIndex,S.cash.groups.length));}else if(S.mode==='data'&&S.data.points.length){S.data.points.splice(S.data.index-1,1);S.data.index=Math.max(1,Math.min(S.data.index,S.data.points.length||1));}showWorksheet();save();}
  function insertWorksheetItem(){if(S.mode==='cf'&&S.cfIndex>0)S.cash.groups.splice(S.cfIndex-1,0,{value:0,frequency:1});else if(S.mode==='data')S.data.points.splice(S.data.index-1,0,{x:0,y:1,frequency:1});showWorksheet();save();}
  function resetAll(){var keepFormat=JSON.parse(JSON.stringify(defaults));S=keepFormat;S.mode='normal';show();save();}
  function handleSecond(key){var mapped=KM.keys.find(function(item){return item.primary===key;}),action=mapped&&mapped.secondaryAction;lastDispatch='secondary:'+String(action||'');S.second=false;
    if(action==='quit'){S.cpt=false;S.mode='normal';show();return true;}if(action==='set'){setWorksheetOption();return true;}
    if(action==='delete'){deleteWorksheetItem();return true;}if(action==='insert'){insertWorksheetItem();return true;}
    if(action==='paymentsMultiplier'){S.tvm.n=num()*S.tvm.py;S.entering=false;display.textContent='N = '+fmt(S.tvm.n);save();return true;}
    if(action==='paymentsWorksheet'){activateWorksheet('py','py');return true;}if(action==='amortization'){activateWorksheet('amort','p1');return true;}if(action==='beginMode'){activateWorksheet('bgn','');return true;}if(action==='clearTvm'){clearTvm();return true;}
    if(action==='hyperbolic'){S.hyp=true;show();return true;}if(action==='sine'){unary('SIN');return true;}if(action==='cosine'){unary('COS');return true;}if(action==='tangent'){unary('TAN');return true;}if(action==='exponential'){unary('eˣ');return true;}
    if(action==='dataWorksheet'){activateWorksheet('data','x');return true;}if(action==='statisticsWorksheet'){activateWorksheet('stat','method');return true;}if(action==='bondWorksheet'){activateWorksheet('bond','sdt');return true;}
    if(action==='round'){unary('ROUND');return true;}if(action==='depreciation'){activateWorksheet('depr','method');return true;}if(action==='percentChange'){activateWorksheet('delta','old');return true;}if(action==='breakEven'){activateWorksheet('breakeven','fixed');return true;}
    if(action==='permutations'){operation('nPr');return true;}if(action==='clearWorksheet'){clearCurrentWorksheet();return true;}if(action==='dateWorksheet'){activateWorksheet('date','dt1');return true;}if(action==='interestConversion'){activateWorksheet('iconv','nom');return true;}if(action==='profitWorksheet'){activateWorksheet('profit','cost');return true;}if(action==='combinations'){operation('nCr');return true;}
    if(action==='memoryWorksheet'){activateWorksheet('mem','');return true;}if(action==='formatWorksheet'){activateWorksheet('format','decimals');return true;}if(action==='reset'){activateWorksheet('reset','');return true;}if(action==='lastAnswer'){setValue(S.lastAnswer||0);show();return true;}
    show();return true;}
  function keyPress(key){
    lastDispatch='primary:'+key;
    if(S.error&&key!=='clear'&&key!=='onoff')return;
    if(key==='2nd'){S.second=!S.second;show();return;}
    if(S.second&&handleSecond(key))return;
    if(/^\d$/.test(key)||key==='.') {digit(key);return;}
    if(key==='cpt'){if(S.mode!=='normal'){computeWorksheet();return;}S.cpt=true;show();return;}
    if(['n','iy','pv','pmt','fv'].indexOf(key)>=0){tvmKey(key);return;}
    if(key==='cf'){S.mode='cf';S.cfIndex=0;S.field='value';showWorksheet();return;}
    if(key==='npv'){S.mode='npv';S.field='rate';showWorksheet();return;}if(key==='irr'){S.mode='irr';S.field='result';showWorksheet();return;}
    if(key==='enter'){if(S.mode==='reset'){resetAll();return;}if(S.mode!=='normal'){storeWorksheet();return;}S.acc=num();S.entering=false;addHistory();return;}
    if(key==='up'){arrows(-1);return;}if(key==='down'){arrows(1);return;}
    if(key==='sto'||key==='rcl'){S.memoryMode=key;indicators.textContent=key.toUpperCase()+' — choose 0–9';return;}
    if(key==='left'){leftParen();return;}if(key==='right'){rightParen();return;}
    if(key==='back'){if(S.entering&&S.input.length>1)S.input=S.input.slice(0,-1);else{S.input='0';S.entering=false;}show();return;}
    if(key==='onoff'){S.mode='normal';S.input='0';S.entering=false;S.error='';S.acc=null;S.op=null;S.aosTokens=[];S.second=false;S.cpt=false;save();root.classList.remove('sf-open');syncPageSpace();var launch=doc.getElementById('sf-calc-fab');if(launch)launch.hidden=false;try{P.localStorage.setItem('sf_calc_open','0');}catch(e){}return;}
    if(key==='sign'){S.input=String(-num());show();return;}if(key==='clear'){clearEntry();return;}
    if(key==='='){equals();return;}if(['+','-','×','÷','yˣ'].indexOf(key)>=0){operation(key);return;}
    if(key==='INV'){S.inv=!S.inv;show();return;}if(['%','√x','x²','1/x','LN'].indexOf(key)>=0){unary(key);return;}
  }
  var keys=KM.keys;
  var grid=root.querySelector('#sf-calc-grid');
  keys.forEach(function(k){var b=doc.createElement('button');b.type='button';b.className='sf-calc-key sf-'+k.style;b.dataset.key=k.primary;b.innerHTML=(k.secondaryLabel?'<span class="alt">'+k.secondaryLabel+'</span>':'')+k.label;b.onclick=function(){if(k.primaryAction)keyPress(k.primaryAction);};grid.appendChild(b);});
  var close=root.querySelector('#sf-calc-close'),expand=root.querySelector('#sf-calc-expand'),theme=root.querySelector('#sf-calc-theme');
  function pageMain(){return doc.querySelector('[data-testid="stMain"],.stMain,section.main,[data-testid="stAppViewContainer"] main');}
  function restorePageSpace(){var saved=P._sfCalcMainLayout;if(!saved||!saved.element)return;Object.keys(saved.properties).forEach(function(name){var prior=saved.properties[name];if(prior.value)saved.element.style.setProperty(name,prior.value,prior.priority||'');else saved.element.style.removeProperty(name);});P._sfCalcMainLayout=null;}
  function syncPageSpace(){
    var open=root.classList.contains('sf-open'),reserve=Math.ceil(root.getBoundingClientRect().width||root.offsetWidth||(root.classList.contains('sf-large')?430:340))+28;
    var reserveSpace=open&&P.innerWidth>650;
    doc.body.classList.toggle('sf-calc-page-open',reserveSpace);doc.body.style.setProperty('--sf-calc-reserved',reserve+'px');
    var main=pageMain();
    if(!reserveSpace){restorePageSpace();return;}
    if(!main)return;
    if(P._sfCalcMainLayout&&P._sfCalcMainLayout.element!==main)restorePageSpace();
    if(!P._sfCalcMainLayout){var names=['box-sizing','width','max-width','margin-right','flex-basis'];var properties={};names.forEach(function(name){properties[name]={value:main.style.getPropertyValue(name),priority:main.style.getPropertyPriority(name)};});P._sfCalcMainLayout={element:main,properties:properties};}
    main.style.setProperty('box-sizing','border-box','important');
    main.style.setProperty('width','calc(100% - '+reserve+'px)','important');
    main.style.setProperty('max-width','calc(100% - '+reserve+'px)','important');
    main.style.setProperty('margin-right',reserve+'px','important');
    main.style.setProperty('flex-basis','calc(100% - '+reserve+'px)','important');
  }
  P._sfCalcSyncPageSpace=syncPageSpace;P._sfCalcRestorePageSpace=restorePageSpace;
  close.onclick=function(){root.classList.remove('sf-open');syncPageSpace();doc.getElementById('sf-calc-fab').hidden=false;try{P.localStorage.setItem('sf_calc_open','0');}catch(e){}};
  function clampY(value){return Math.max(8,Math.min(value,Math.max(8,P.innerHeight-root.offsetHeight-8)));}
  function setY(value){root.style.top=clampY(Number(value)||8)+'px';}
  try{var savedY=Number(P.localStorage.getItem('sf_calc_y'));if(Number.isFinite(savedY))setY(savedY);}catch(e){}
  var head=root.querySelector('.sf-calc-head'),drag=null;
  head.onpointerdown=function(e){if(e.target.closest('button'))return;drag={pointer:e.pointerId,start:e.clientY,top:parseFloat(root.style.top)||root.getBoundingClientRect().top};head.setPointerCapture(e.pointerId);e.preventDefault();};
  head.onpointermove=function(e){if(!drag||e.pointerId!==drag.pointer)return;setY(drag.top+e.clientY-drag.start);};
  head.onpointerup=head.onpointercancel=function(e){if(!drag||e.pointerId!==drag.pointer)return;drag=null;try{P.localStorage.setItem('sf_calc_y',String(parseFloat(root.style.top)||8));}catch(err){}};
  expand.onclick=function(){root.classList.toggle('sf-large');syncPageSpace();setY(parseFloat(root.style.top)||root.getBoundingClientRect().top);try{P.localStorage.setItem('sf_calc_large',root.classList.contains('sf-large')?'1':'0');}catch(e){}};
  theme.onclick=function(){root.classList.toggle('sf-dark');try{P.localStorage.setItem('sf_calc_dark',root.classList.contains('sf-dark')?'1':'0');}catch(e){}};
  if(P._sfCalcKeydown)doc.removeEventListener('keydown',P._sfCalcKeydown);
  P._sfCalcKeydown=function(e){if(!root.classList.contains('sf-open'))return;if(e.target&&/input|textarea|select/i.test(e.target.tagName))return;var map={'*':'×','/':'÷','Enter':'=','Backspace':'clear','Escape':'clear'};var key=map[e.key]||e.key;if(/^\d$/.test(key)||['.','+','-','×','÷','='].indexOf(key)>=0){e.preventDefault();keyPress(key);}};
  doc.addEventListener('keydown',P._sfCalcKeydown);
  if(P._sfCalcResize)P.removeEventListener('resize',P._sfCalcResize);
  P._sfCalcResize=function(){syncPageSpace();setY(parseFloat(root.style.top)||8);};P.addEventListener('resize',P._sfCalcResize);
  P.SFCalculatorTestAPI={click:function(primary){var button=Array.prototype.find.call(grid.children,function(item){return item.dataset.key===primary;});if(!button)throw Error('Unknown key '+primary);button.onclick();},reset:function(){S=JSON.parse(JSON.stringify(defaults));lastDispatch='';show();save();},snapshot:function(){return {state:JSON.parse(JSON.stringify(S)),display:display.textContent,indicators:indicators.textContent,lastDispatch:lastDispatch};}};
  syncPageSpace();show();save();
}());
"""


def inject_financial_calculator() -> None:
    """Install the persistent calculator drawer into the parent Streamlit page."""
    core = _CORE_PATH.read_text(encoding="utf-8")
    keymap = _KEYMAP_PATH.read_text(encoding="utf-8")
    bundle = r"""
<script>
(function () {
  'use strict';
  var P=window.parent;if(!P||!P.document)return;var doc=P.document;
  __CORE_SOURCE__
  __KEYMAP_SOURCE__
  P.SFCalculatorMath=window.SFCalculatorMath;
  P.SFCalculatorKeyMap=window.SFCalculatorKeyMap;
  if(P._sfCalcRestorePageSpace)P._sfCalcRestorePageSpace();var old=doc.getElementById('sf-calc-drawer');if(old)old.remove();doc.body.classList.remove('sf-calc-page-open');
  var oldFab=doc.getElementById('sf-calc-fab');if(oldFab)oldFab.remove();
  var style=doc.getElementById('sf-calc-style');if(!style){style=doc.createElement('style');style.id='sf-calc-style';doc.head.appendChild(style);}style.textContent=__CSS__;
  var oldCore=doc.getElementById('sf-calc-core');if(oldCore)oldCore.remove();
  var oldMap=doc.getElementById('sf-calc-keymap');if(oldMap)oldMap.remove();
  var fab=doc.createElement('button');fab.id='sf-calc-fab';fab.type='button';fab.innerHTML='&#129518;';fab.title='Open financial calculator';fab.setAttribute('aria-label','Open financial calculator');doc.body.appendChild(fab);
  var drawer=doc.createElement('aside');drawer.id='sf-calc-drawer';drawer.setAttribute('aria-label','Financial calculator');drawer.innerHTML=__HTML__;doc.body.appendChild(drawer);
  function stored(key){try{return P.localStorage.getItem(key)==='1';}catch(e){return false;}}
  if(stored('sf_calc_large'))drawer.classList.add('sf-large');if(stored('sf_calc_dark'))drawer.classList.add('sf-dark');
  function open(){drawer.classList.add('sf-open');doc.body.classList.add('sf-calc-page-open');fab.hidden=true;if(P._sfCalcSyncPageSpace)P._sfCalcSyncPageSpace();try{P.localStorage.setItem('sf_calc_open','1');}catch(e){}}
  fab.onclick=open;if(stored('sf_calc_open'))open();
  __LOGIC_SOURCE__
}());
</script>
"""
    if any("</script" in source.lower() for source in (core, keymap, _LOGIC)):
        raise ValueError("Calculator JavaScript cannot contain a closing script tag")
    bundle = (
        bundle.replace("__CSS__", json.dumps(_CSS))
        .replace("__CORE_SOURCE__", core)
        .replace("__KEYMAP_SOURCE__", keymap)
        .replace("__HTML__", json.dumps(_HTML))
        .replace("__LOGIC_SOURCE__", _LOGIC)
    )
    components.html(bundle, height=0, scrolling=False)
