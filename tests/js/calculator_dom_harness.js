/* Minimal DOM harness that executes the exact calculator UI logic and clicks
 * the actual generated button handlers without requiring a network browser. */
'use strict';

const fs = require('fs');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));

class ClassList {
  constructor(initial) { this.values = new Set(initial || []); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
  toggle(value, force) {
    const enabled = force === undefined ? !this.contains(value) : !!force;
    if (enabled) this.add(value); else this.remove(value);
    return enabled;
  }
}

class Element {
  constructor(tagName, id) {
    this.tagName = String(tagName || 'div').toUpperCase();
    this.id = id || '';
    this.children = [];
    this.dataset = {};
    this.textContent = '';
    this.innerHTML = '';
    this.hidden = false;
    this.className = '';
    this.classList = new ClassList();
    this.style = {
      top: '', values: {}, priorities: {},
      setProperty(name, value, priority) { this.values[name] = value; this.priorities[name] = priority || ''; },
      removeProperty(name) { delete this.values[name]; delete this.priorities[name]; },
      getPropertyValue(name) { return this.values[name] || ''; },
      getPropertyPriority(name) { return this.priorities[name] || ''; },
    };
  }
  appendChild(child) { this.children.push(child); return child; }
  setPointerCapture() {}
  closest(selector) { return selector === 'button' && this.tagName === 'BUTTON' ? this : null; }
  getBoundingClientRect() { return {top: Number.parseFloat(this.style.top) || 48, width: this.classList.contains('sf-large') ? 430 : (this.offsetWidth || 340)}; }
}

const display = new Element('div', 'sf-calc-display');
const indicators = new Element('div', 'sf-calc-indicators');
const grid = new Element('div', 'sf-calc-grid');
const close = new Element('button', 'sf-calc-close');
const expand = new Element('button', 'sf-calc-expand');
const theme = new Element('button', 'sf-calc-theme');
const head = new Element('div');
const fab = new Element('button', 'sf-calc-fab');
const root = new Element('aside', 'sf-calc-drawer');
root.offsetHeight = 620;
root.classList.add('sf-open');

const selectors = {
  '#sf-calc-display': display,
  '#sf-calc-indicators': indicators,
  '#sf-calc-grid': grid,
  '#sf-calc-close': close,
  '#sf-calc-expand': expand,
  '#sf-calc-theme': theme,
  '.sf-calc-head': head,
};
root.querySelector = selector => selectors[selector] || null;

const storage = new Map();
const body = new Element('body');
const main = new Element('main');
const document = {
  body,
  querySelector(selector) { return selector.includes('stMain') || selector.includes('section.main') ? main : null; },
  getElementById(id) { return id === 'sf-calc-drawer' ? root : id === 'sf-calc-fab' ? fab : null; },
  createElement(tag) { return new Element(tag); },
  addEventListener() {},
  removeEventListener() {},
};
const parent = {
  document,
  innerHeight: 1080,
  SFCalculatorMath: require(payload.corePath),
  SFCalculatorKeyMap: require(payload.keymapPath),
  localStorage: {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
  },
  addEventListener() {},
  removeEventListener() {},
};
global.window = {parent};
eval(payload.logic);

const api = parent.SFCalculatorTestAPI;
const map = parent.SFCalculatorKeyMap;
const primaryCoverage = [];
const secondaryCoverage = [];

for (const item of map.keys.filter(item => item.primary)) {
  api.reset();
  api.click(item.primary);
  primaryCoverage.push({primary: item.primary, label: item.label, dispatch: api.snapshot().lastDispatch});
  if (item.secondaryAction) {
    api.reset();
    api.click('2nd');
    api.click(item.primary);
    secondaryCoverage.push({
      primary: item.primary,
      label: item.secondaryLabel,
      action: item.secondaryAction,
      dispatch: api.snapshot().lastDispatch,
    });
  }
}

const traces = {};
for (const sequence of payload.sequences || []) {
  api.reset();
  traces[sequence.name] = [];
  for (const primary of sequence.keys) {
    api.click(primary);
    traces[sequence.name].push({key: primary, ...api.snapshot()});
  }
}

/* Prove persistence across destruction/recreation of the UI state machine. */
api.reset();
for (const primary of ['4', '2', 'sto', '3', '5', 'n']) api.click(primary);
const beforeRecreation = api.snapshot();
grid.children = [];
eval(payload.logic);
const afterRecreation = parent.SFCalculatorTestAPI.snapshot();

root.classList.add('sf-open');
parent._sfCalcSyncPageSpace();
const openLayout = {...main.style.values};
close.onclick();
const closedLayout = {...main.style.values};
root.classList.add('sf-open');
parent._sfCalcSyncPageSpace();
expand.onclick();
const expandedLayout = {...main.style.values};

process.stdout.write(JSON.stringify({primaryCoverage, secondaryCoverage, traces,
  persistence:{beforeRecreation,afterRecreation}, layout:{openLayout,closedLayout,expandedLayout}}));
