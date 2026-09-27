/* Declarative BA II Plus key map shared by the rendered keypad and coverage tests. */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SFCalculatorKeyMap = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function key(primary, label, secondaryLabel, secondaryAction, style) {
    return {primary:primary,primaryAction:primary,label:label,secondaryLabel:secondaryLabel||'',secondaryAction:secondaryAction||'',style:style||'darkkey'};
  }
  var rows = [
    [key('cpt','CPT','QUIT','quit'),key('enter','ENTER','SET','set'),key('up','↑','DEL','delete'),key('down','↓','INS','insert'),key('onoff','ON/OFF')],
    [key('2nd','2ND','','','gold'),key('cf','CF'),key('npv','NPV'),key('irr','IRR'),key('back','→')],
    [key('n','N','xP/Y','paymentsMultiplier','fin'),key('iy','I/Y','P/Y','paymentsWorksheet','fin'),key('pv','PV','AMORT','amortization','fin'),key('pmt','PMT','BGN','beginMode','fin'),key('fv','FV','CLR TVM','clearTvm','fin')],
    [key('%','%','HYP','hyperbolic'),key('√x','√x','SIN','sine'),key('x²','x²','COS','cosine'),key('1/x','1/x','TAN','tangent'),key('÷','÷')],
    [key('INV','INV','eˣ','exponential'),key('left','(','DATA','dataWorksheet'),key('right',')','STAT','statisticsWorksheet'),key('yˣ','yˣ','BOND','bondWorksheet'),key('×','×')],
    [key('LN','LN','ROUND','round'),key('7','7','DEPR','depreciation','num'),key('8','8','Δ%','percentChange','num'),key('9','9','BRKEVN','breakEven','num'),key('-','−','nPr','permutations')],
    [key('sto','STO'),key('4','4','','','num'),key('5','5','','','num'),key('6','6','','','num'),key('','','','','spacer')],
    [key('rcl','RCL','CLR WORK','clearWorksheet'),key('1','1','DATE','dateWorksheet','num'),key('2','2','ICONV','interestConversion','num'),key('3','3','PROFIT','profitWorksheet','num'),key('+','+','nCr','combinations')],
    [key('clear','CE/C'),key('0','0','MEM','memoryWorksheet','num'),key('.','.','FORMAT','formatWorksheet','num'),key('sign','+/−','RESET','reset','num'),key('=','=','ANS','lastAnswer')]
  ];
  return {rows:rows,keys:rows.reduce(function(all,row){return all.concat(row);},[])};
}));
