(() => {
  const doc = window.parent.document;
  if (doc.__practiceSwipeCleanup) doc.__practiceSwipeCleanup();
  const question = window.practiceSwipeQuestion;
  if (doc.__practiceSwipeQuestion !== undefined && doc.__practiceSwipeQuestion !== question) {
    doc.querySelector('.st-key-practice_swipe_card')?.scrollIntoView({block:'start'});
  }
  doc.__practiceSwipeQuestion = question;
  let start = null;
  let busy = false;
  const down = e => {
    if (!e.isPrimary || e.button !== 0 || busy) return;
    if (!e.target.closest('.st-key-practice_swipe_card')) return;
    if (e.target.closest('button, input, textarea:not([readonly]), label, select, a, [role="button"], [contenteditable="true"]')) return;
    // Desktop dragging should navigate instead of selecting the question text.
    // Touch scrolling is controlled independently by touch-action: pan-y.
    if (e.pointerType === 'mouse') e.preventDefault();
    start = {x:e.clientX, y:e.clientY, id:e.pointerId};
  };
  const move = e => {
    if (start && (e.pointerId !== start.id || Math.abs(e.clientY - start.y) > 45)) start = null;
  };
  const up = e => {
    const origin = start;
    start = null;
    if (!origin || origin.id !== e.pointerId || busy) return;
    const dx = e.clientX - origin.x, dy = e.clientY - origin.y;
    if (Math.abs(dx) < 80 || Math.abs(dx) < Math.abs(dy) * 1.8) return;
    const key = dx < 0 ? 'swipe_next' : 'swipe_previous';
    const button = doc.querySelector(`.st-key-${key} button`);
    if (button && !button.disabled) {
      busy = true;
      button.click();
    }
  };
  const cancel = () => {start = null;};
  doc.addEventListener('pointerdown', down);
  doc.addEventListener('pointermove', move, {passive:true});
  doc.addEventListener('pointerup', up);
  doc.addEventListener('pointercancel', cancel);
  const cleanup = () => {
    doc.removeEventListener('pointerdown', down);
    doc.removeEventListener('pointermove', move);
    doc.removeEventListener('pointerup', up);
    doc.removeEventListener('pointercancel', cancel);
  };
  doc.__practiceSwipeCleanup = cleanup;
  window.addEventListener('pagehide', cleanup, {once:true});
})();
