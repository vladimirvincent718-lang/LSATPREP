export function totalStatus(values) {
  if (values.some(v => typeof v !== 'number' || !Number.isFinite(v) || v < 0 || v > 100)) {
    return {status: 'invalid', text: 'Enter 0–100 in every field', total: null};
  }
  const total = Math.round(values.reduce((sum, value) => sum + value, 0) * 100) / 100;
  const delta = Math.round((total - 100) * 100) / 100;
  if (delta === 0) return {status: 'balanced', text: 'Exactly 100% · Balanced', total};
  return {status: delta > 0 ? 'over' : 'under', total,
    text: `${Math.abs(delta)} percentage ${Math.abs(delta) === 1 ? 'point' : 'points'} ${delta > 0 ? 'over' : 'under'} 100%`};
}

export function roundedCounts(weights, total, orderedKeys = Object.keys(weights)) {
  if (totalStatus(Object.values(weights)).status !== 'balanced') return null;
  const sum = Object.values(weights).reduce((a, b) => a + b, 0);
  const raw = Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, total * value / sum]));
  const counts = Object.fromEntries(Object.entries(raw).map(([key, value]) => [key, Math.floor(value)]));
  const remainder = total - Object.values(counts).reduce((a, b) => a + b, 0);
  [...orderedKeys].sort((a, b) => (raw[b] - counts[b]) - (raw[a] - counts[a]))
    .slice(0, remainder).forEach(key => counts[key]++);
  return counts;
}

export default function({parentElement, data, setStateValue}) {
  let root = parentElement.querySelector('.allocation-editor');
  if (!root) {
    root = document.createElement('div');
    root.className = 'allocation-editor';
    parentElement.appendChild(root);
    root.weights = {courses: {}, modules: {}};
    root.countLabels = {};
    root.courseLabels = {};
    root.totals = {};
    const make = (tag, text, className, parent) => {
      const element = document.createElement(tag);
      if (text) element.textContent = text;
      if (className) element.className = className;
      parent.appendChild(element);
      return element;
    };
    const total = (title, parent) => {
      const box = make('div', '', 'total', parent);
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      make('span', title, '', box);
      box.number = make('strong', '', '', box);
      box.message = make('span', '', '', box);
      return box;
    };
    let fieldIndex = 0;
    const field = (title, value, parent, update) => {
      const row = make('div', '', 'weight-row', parent);
      const label = make('label', title, '', row);
      const controls = make('div', '', 'number-field', row);
      const input = make('input', '', '', controls);
      input.type = 'number'; input.min = '0'; input.max = '100'; input.step = '0.01';
      input.value = value; input.id = `allocation-${data.signature}-${fieldIndex++}`;
      label.htmlFor = input.id;
      const commit = () => {
        const value = input.value === '' ? null : Number(input.value);
        input.setAttribute('aria-invalid', String(value === null || value < 0 || value > 100));
        update(value);
        root.paint();
        // Paint synchronously; only the lightweight fragment receives state.
        root.send('weights', JSON.parse(JSON.stringify(root.weights)));
      };
      input.addEventListener('input', commit);
      for (const [text, step] of [['−', -1], ['+', 1]]) {
        const button = make('button', text, '', controls);
        button.type = 'button'; button.setAttribute('aria-label', `${step > 0 ? 'Increase' : 'Decrease'} ${title}`);
        button.onclick = () => {
          input.value = Math.max(0, Math.min(100, Math.round((Number(input.value) + step) * 100) / 100));
          commit();
        };
      }
      return make('span', '', 'count', row);
    };
    for (const course of data.courses) {
      const cid = course.id;
      root.weights.courses[cid] = course.weight;
      root.weights.modules[cid] = {};
      root.countLabels[cid] = {};
      const details = make('details', '', '', root); details.open = true;
      make('summary', `${course.title} — modules / chapters`, '', details);
      for (const module of course.modules) {
        root.weights.modules[cid][module.id] = module.weight;
        root.countLabels[cid][module.id] = field(`${module.title} — % of course`, module.weight, details,
          value => root.weights.modules[cid][module.id] = value);
      }
      root.totals[cid] = total('Modules / chapters total', details);
      const footer = make('div', '', 'course-weight', details);
      root.courseLabels[cid] = field(`${course.title} — % of exam`, course.weight, footer,
        value => root.weights.courses[cid] = value);
    }
    root.examTotal = total('All courses · exam allocation', root);
    make('p', 'Question counts are rounded to whole questions. Each course’s modules / chapters and the overall exam allocation should total 100%.', 'hint', root);
    root.paint = () => {
      const showTotal = (element, values) => {
        const summary = totalStatus(values);
        element.dataset.status = summary.status;
        element.number.textContent = summary.total === null ? '—' : `${summary.total}%`;
        element.message.textContent = summary.text;
      };
      showTotal(root.examTotal, Object.values(root.weights.courses));
      const courseCounts = roundedCounts(root.weights.courses, root.config.total, root.config.courses.map(c => c.id));
      for (const course of root.config.courses) {
        const cid = course.id;
        showTotal(root.totals[cid], Object.values(root.weights.modules[cid]));
        root.courseLabels[cid].textContent = courseCounts ? `${courseCounts[cid]} questions` : 'Balance to 100%';
        const counts = courseCounts && roundedCounts(root.weights.modules[cid], courseCounts[cid], course.modules.map(m => m.id));
        for (const module of course.modules) {
          root.countLabels[cid][module.id].textContent = counts ? `${counts[module.id]} questions` : 'Balance to 100%';
        }
      }
    };
  }
  // Retain input nodes and focus when Python acknowledges an edit.
  root.config = data;
  root.send = setStateValue;
  root.paint();
}
