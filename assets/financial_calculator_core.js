/*
 * StudyForge financial calculator math core.
 * BA II Plus-style behavior and formulas implemented independently from the
 * Texas Instruments guidebook. UI design informed by the MIT-licensed
 * ba2plus-calculator project by Parth Khanna (2026).
 */
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SFCalculatorMath = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function finite(value, fallback) {
    var number = Number(value);
    return Number.isFinite(number) ? number : (fallback || 0);
  }

  function tvmEquation(rate, n, pv, pmt, fv, begin) {
    rate = finite(rate); n = finite(n); pv = finite(pv);
    pmt = finite(pmt); fv = finite(fv);
    if (Math.abs(rate) < 1e-12) return pv + pmt * n + fv;
    var growth = Math.pow(1 + rate, n);
    return pv * growth + pmt * (1 + (begin ? rate : 0)) * ((growth - 1) / rate) + fv;
  }

  function rootByScan(fn, low, high, steps) {
    var previousX = low;
    var previousY = fn(previousX);
    if (Math.abs(previousY) < 1e-10) return previousX;
    for (var i = 1; i <= steps; i += 1) {
      var x = low + (high - low) * i / steps;
      var y = fn(x);
      if (!Number.isFinite(y)) continue;
      if (Math.abs(y) < 1e-10) return x;
      if (Number.isFinite(previousY) && previousY * y < 0) {
        var a = previousX, b = x, fa = previousY;
        for (var j = 0; j < 160; j += 1) {
          var middle = (a + b) / 2;
          var fm = fn(middle);
          if (!Number.isFinite(fm)) { a = middle; continue; }
          if (Math.abs(fm) < 1e-11) return middle;
          if (fa * fm <= 0) b = middle;
          else { a = middle; fa = fm; }
        }
        return (a + b) / 2;
      }
      previousX = x; previousY = y;
    }
    throw new RangeError('No solution');
  }

  function solveTvm(target, values) {
    var n = finite(values.n), iy = finite(values.iy), pv = finite(values.pv);
    var pmt = finite(values.pmt), fv = finite(values.fv);
    var py = Math.max(1, finite(values.py, 1));
    var cy = Math.max(1, finite(values.cy, py));
    var begin = !!values.begin;
    /* Convert the nominal annual I/Y rate into an effective payment-period
       rate, including the BA II Plus P/Y and C/Y worksheet convention. */
    var rate = Math.pow(1 + (iy / 100) / cy, cy / py) - 1;
    var growth = Math.pow(1 + rate, n);
    var annuity = Math.abs(rate) < 1e-12 ? n : ((growth - 1) / rate) * (1 + (begin ? rate : 0));
    if (target === 'fv') return -(pv * growth + pmt * annuity);
    if (target === 'pv') return -(pmt * annuity + fv) / growth;
    if (target === 'pmt') {
      if (Math.abs(annuity) < 1e-14) throw new RangeError('Invalid inputs');
      return -(pv * growth + fv) / annuity;
    }
    if (target === 'iy') {
      var solvedRate = rootByScan(function (r) {
        return tvmEquation(r, n, pv, pmt, fv, begin);
      }, -0.999999, 10, 2200);
      return (Math.pow(1 + solvedRate, py / cy) - 1) * cy * 100;
    }
    if (target === 'n') {
      return rootByScan(function (periods) {
        return tvmEquation(rate, periods, pv, pmt, fv, begin);
      }, 0.000001, 10000, 3000);
    }
    throw new RangeError('Unknown TVM register');
  }

  function periodicRate(values) {
    var py = Math.max(1, finite(values.py, 1));
    var cy = Math.max(1, finite(values.cy, py));
    return Math.pow(1 + finite(values.iy) / 100 / cy, cy / py) - 1;
  }

  function expandCashFlows(groups) {
    var expanded = [];
    (groups || []).forEach(function (group) {
      var frequency = Math.max(1, Math.floor(finite(group.frequency, 1)));
      for (var i = 0; i < frequency; i += 1) expanded.push(finite(group.value));
    });
    return expanded;
  }

  function npv(ratePercent, cf0, groups) {
    var rate = finite(ratePercent) / 100;
    if (rate <= -1) throw new RangeError('Invalid discount rate');
    var flows = expandCashFlows(groups);
    var result = finite(cf0);
    flows.forEach(function (flow, index) {
      result += flow / Math.pow(1 + rate, index + 1);
    });
    return result;
  }

  function irr(cf0, groups) {
    return rootByScan(function (rate) {
      return npv(rate * 100, cf0, groups);
    }, -0.999999, 10, 4400) * 100;
  }

  function bondPrice(face, couponRate, yieldRate, years, frequency) {
    face = finite(face, 100); couponRate = finite(couponRate);
    yieldRate = finite(yieldRate); years = finite(years);
    frequency = Math.max(1, Math.floor(finite(frequency, 2)));
    var periods = Math.max(0, Math.round(years * frequency));
    var coupon = face * couponRate / 100 / frequency;
    var rate = yieldRate / 100 / frequency;
    if (Math.abs(rate) < 1e-12) return coupon * periods + face;
    return coupon * (1 - Math.pow(1 + rate, -periods)) / rate + face * Math.pow(1 + rate, -periods);
  }

  function bondYield(price, face, couponRate, years, frequency) {
    price = finite(price); frequency = Math.max(1, Math.floor(finite(frequency, 2)));
    return rootByScan(function (annualRate) {
      return bondPrice(face, couponRate, annualRate * 100, years, frequency) - price;
    }, -0.999999, 10, 5000) * 100;
  }

  function amortization(values, firstPayment, lastPayment) {
    var first = Math.max(1, Math.floor(finite(firstPayment, 1)));
    var last = Math.max(first, Math.floor(finite(lastPayment, first)));
    var rate = periodicRate(values), balance = finite(values.pv);
    var payment = finite(values.pmt), principalTotal = 0, interestTotal = 0;
    for (var period = 1; period <= last; period += 1) {
      var interest, principal;
      if (values.begin) {
        principal = payment;
        balance += principal;
        interest = -balance * rate;
        balance -= interest;
      } else {
        interest = -balance * rate;
        principal = payment - interest;
        balance += principal;
      }
      if (period >= first) { principalTotal += principal; interestTotal += interest; }
    }
    return {balance: balance, principal: principalTotal, interest: interestTotal};
  }

  function statistics(points, oneVariable) {
    var expanded = [];
    (points || []).forEach(function (point) {
      var frequency = Math.max(1, Math.floor(finite(point.frequency, oneVariable ? finite(point.y, 1) : 1)));
      for (var i = 0; i < frequency; i += 1) expanded.push({x: finite(point.x), y: finite(point.y)});
    });
    var n = expanded.length;
    if (!n) throw new RangeError('No statistical data');
    var sx = 0, sy = 0, sx2 = 0, sy2 = 0, sxy = 0;
    expanded.forEach(function (p) { sx += p.x; sy += p.y; sx2 += p.x*p.x; sy2 += p.y*p.y; sxy += p.x*p.y; });
    var meanX = sx/n, meanY = sy/n;
    var sampleX = n > 1 ? Math.sqrt(Math.max(0,(sx2-sx*sx/n)/(n-1))) : 0;
    var popX = Math.sqrt(Math.max(0,(sx2-sx*sx/n)/n));
    var denom = n*sx2-sx*sx;
    var b = denom ? (n*sxy-sx*sy)/denom : 0;
    var a = meanY-b*meanX;
    var corrDenom = Math.sqrt(Math.max(0,(n*sx2-sx*sx)*(n*sy2-sy*sy)));
    return {n:n,meanX:meanX,sampleX:sampleX,populationX:popX,sumX:sx,sumX2:sx2,
      meanY:meanY,sampleY:n>1?Math.sqrt(Math.max(0,(sy2-sy*sy/n)/(n-1))):0,
      populationY:Math.sqrt(Math.max(0,(sy2-sy*sy/n)/n)),sumY:sy,sumY2:sy2,
      a:oneVariable?0:a,b:oneVariable?0:b,r:oneVariable?0:(corrDenom?(n*sxy-sx*sy)/corrDenom:0)};
  }

  function nominalToEffective(nominal, compoundsPerYear) {
    var m = Math.max(1, finite(compoundsPerYear, 1));
    return (Math.pow(1 + finite(nominal)/100/m, m) - 1) * 100;
  }

  function effectiveToNominal(effective, compoundsPerYear) {
    var m = Math.max(1, finite(compoundsPerYear, 1));
    return m * (Math.pow(1 + finite(effective)/100, 1/m) - 1) * 100;
  }

  function daysBetween(firstDate, secondDate, method) {
    var a = new Date(firstDate), b = new Date(secondDate);
    if (!Number.isFinite(a.getTime()) || !Number.isFinite(b.getTime())) throw new RangeError('Invalid date');
    if (method === '360') {
      var d1=Math.min(a.getUTCDate(),30), d2=a.getUTCDate()===31?Math.min(b.getUTCDate(),30):b.getUTCDate();
      return (b.getUTCFullYear()-a.getUTCFullYear())*360+(b.getUTCMonth()-a.getUTCMonth())*30+d2-d1;
    }
    return Math.round((Date.UTC(b.getUTCFullYear(),b.getUTCMonth(),b.getUTCDate())-Date.UTC(a.getUTCFullYear(),a.getUTCMonth(),a.getUTCDate()))/86400000);
  }

  function profitMargin(target, values) {
    var cost=finite(values.cost), sell=finite(values.sell), margin=finite(values.margin);
    if(target==='margin')return (sell-cost)/sell*100;
    if(target==='sell')return cost/(1-margin/100);
    if(target==='cost')return sell*(1-margin/100);
    throw new RangeError('Unknown profit variable');
  }

  function breakEven(target, values) {
    var fixed=finite(values.fixed), variable=finite(values.variable), price=finite(values.price);
    var quantity=finite(values.quantity), profit=finite(values.profit);
    if(target==='profit')return (price-variable)*quantity-fixed;
    if(target==='quantity')return (fixed+profit)/(price-variable);
    if(target==='price')return variable+(fixed+profit)/quantity;
    if(target==='fixed')return (price-variable)*quantity-profit;
    if(target==='variable')return price-(fixed+profit)/quantity;
    throw new RangeError('Unknown break-even variable');
  }

  function straightLineDepreciation(cost, salvage, life, year) {
    cost=finite(cost);salvage=finite(salvage);life=Math.max(1,finite(life,1));year=Math.max(1,Math.floor(finite(year,1)));
    var annual=(cost-salvage)/life, elapsed=Math.min(year,Math.ceil(life));
    var dep=year<=Math.ceil(life)?Math.min(annual,Math.max(0,cost-salvage-annual*(year-1))):0;
    var rbv=Math.max(salvage,cost-annual*elapsed);
    return {depreciation:dep,remainingBookValue:rbv,remainingDepreciableValue:Math.max(0,rbv-salvage)};
  }

  function depreciation(method, cost, salvage, life, year, decliningPercent) {
    method=String(method||'SL').toUpperCase();cost=finite(cost);salvage=finite(salvage);
    life=Math.max(1,finite(life,1));year=Math.max(1,Math.floor(finite(year,1)));
    if(method==='SL')return straightLineDepreciation(cost,salvage,life,year);
    var book=cost, dep=0;
    for(var y=1;y<=year;y+=1){
      if(method==='SYD')dep=(cost-salvage)*Math.max(0,life-y+1)/(life*(life+1)/2);
      else dep=book*Math.max(0,finite(decliningPercent,200))/100/life;
      dep=Math.min(Math.max(0,dep),Math.max(0,book-salvage));book-=dep;
    }
    return {depreciation:dep,remainingBookValue:book,remainingDepreciableValue:Math.max(0,book-salvage)};
  }

  function percentChange(oldValue, newValue, periods) {
    oldValue=finite(oldValue);newValue=finite(newValue);periods=Math.max(1,finite(periods,1));
    if(!oldValue)throw new RangeError('Invalid old value');
    return (Math.pow(newValue/oldValue,1/periods)-1)*100;
  }

  function factorial(value) {
    var n=Math.floor(finite(value));
    if(n<0||n>69||n!==finite(value))throw new RangeError('Invalid factorial');
    var result=1;for(var i=2;i<=n;i+=1)result*=i;return result;
  }

  function combinations(n, r) { return factorial(n)/(factorial(r)*factorial(n-r)); }
  function permutations(n, r) { return factorial(n)/factorial(n-r); }

  function percentOperand(base, operator, percent) {
    return (operator==='+'||operator==='-') ? finite(base)*finite(percent)/100 : finite(percent)/100;
  }

  function evaluateExpression(tokens) {
    var values=[],ops=[],precedence={'+':1,'-':1,'×':2,'÷':2,'yˣ':3,'nCr':3,'nPr':3};
    function calculate(a,op,b){if(op==='+')return a+b;if(op==='-')return a-b;if(op==='×')return a*b;if(op==='÷')return a/b;if(op==='yˣ')return Math.pow(a,b);if(op==='nCr')return combinations(a,b);if(op==='nPr')return permutations(a,b);throw new RangeError('Unknown operator');}
    function apply(){var op=ops.pop(),b=values.pop(),a=values.pop();values.push(calculate(a,op,b));}
    (tokens||[]).forEach(function(t){if(typeof t==='number')values.push(t);else if(t==='(')ops.push(t);else if(t===')'){while(ops.length&&ops[ops.length-1]!=='(')apply();if(ops.pop()!=='(')throw new RangeError('Parenthesis mismatch');}else{while(ops.length&&ops[ops.length-1]!=='('&&(precedence[ops[ops.length-1]]>precedence[t]||(precedence[ops[ops.length-1]]===precedence[t]&&t!=='yˣ')))apply();ops.push(t);}});
    while(ops.length){if(ops[ops.length-1]==='(')throw new RangeError('Parenthesis mismatch');apply();}
    if(values.length!==1||!Number.isFinite(values[0]))throw new RangeError('Invalid expression');return values[0];
  }

  return {
    tvmEquation: tvmEquation,
    solveTvm: solveTvm,
    expandCashFlows: expandCashFlows,
    npv: npv,
    irr: irr,
    bondPrice: bondPrice,
    bondYield: bondYield,
    amortization: amortization,
    statistics: statistics,
    nominalToEffective: nominalToEffective,
    effectiveToNominal: effectiveToNominal,
    daysBetween: daysBetween,
    profitMargin: profitMargin,
    breakEven: breakEven,
    straightLineDepreciation: straightLineDepreciation,
    depreciation: depreciation,
    percentChange: percentChange,
    factorial: factorial,
    combinations: combinations,
    permutations: permutations,
    percentOperand: percentOperand,
    evaluateExpression: evaluateExpression
  };
}));
