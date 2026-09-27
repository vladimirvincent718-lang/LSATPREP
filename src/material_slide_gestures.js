(() => {
  const doc = window.parent.document;
  const {prefix} = window.slideViewerConfig;
  const registry = doc.__materialSlideCleanup ||= {};
  registry[prefix]?.();
  const selector = `.st-key-${prefix}_frame`;
  let start = null, busy = false;
  const frame = () => doc.querySelector(selector);
  const editable = target => target.closest('input, textarea, select, button, a, [contenteditable="true"]');
  const navigate = delta => {
    const host = frame();
    if (busy || !host || !host.getClientRects().length) return;
    const button = doc.querySelector(`.st-key-${prefix}_${delta > 0 ? 'next' : 'previous'} button`);
    if (button && !button.disabled) {
      busy = true;
      doc.__materialSlideFocus = prefix;
      button.click();
    }
  };
  const down = e => {
    if (!e.isPrimary || e.button !== 0 || busy || !e.target.closest(selector) || editable(e.target)) return;
    frame()?.focus({preventScroll:true});
    if (e.pointerType === 'mouse') e.preventDefault();
    start = {x:e.clientX, y:e.clientY, id:e.pointerId};
  };
  const move = e => {
    if (start && (e.pointerId !== start.id || Math.abs(e.clientY-start.y) > 50)) start = null;
  };
  const up = e => {
    const origin = start;
    start = null;
    if (!origin || origin.id !== e.pointerId) return;
    const dx = e.clientX-origin.x, dy = e.clientY-origin.y;
    if (Math.abs(dx) >= 65 && Math.abs(dx) > Math.abs(dy)*1.8) navigate(dx < 0 ? 1 : -1);
  };
  const key = e => {
    if (e.altKey || e.ctrlKey || e.metaKey || editable(e.target)) return;
    if (!e.target.closest(selector)) return;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      navigate(e.key === 'ArrowRight' ? 1 : -1);
    }
  };
  const cancel = () => {start = null;};
  const arm = () => {
    const host = frame();
    if (!host) return;
    host.tabIndex = 0;
    host.setAttribute('role', 'region');
    host.setAttribute('aria-label', 'Slide viewer. Use left and right arrow keys or swipe to change slides.');
    if (doc.__materialSlideFocus === prefix) {
      host.focus({preventScroll:true});
      delete doc.__materialSlideFocus;
    }
  };
  arm();
  const observer = new MutationObserver(arm);
  observer.observe(doc.body, {childList:true, subtree:true});
  doc.addEventListener('pointerdown', down);
  doc.addEventListener('pointermove', move, {passive:true});
  doc.addEventListener('pointerup', up);
  doc.addEventListener('pointercancel', cancel);
  doc.addEventListener('keydown', key);
  const cleanup = () => {
    observer.disconnect();
    doc.removeEventListener('pointerdown', down);
    doc.removeEventListener('pointermove', move);
    doc.removeEventListener('pointerup', up);
    doc.removeEventListener('pointercancel', cancel);
    doc.removeEventListener('keydown', key);
    if (registry[prefix] === cleanup) delete registry[prefix];
  };
  registry[prefix] = cleanup;
  window.addEventListener('pagehide', cleanup, {once:true});
})();
