(() => {
  const doc = window.parent.document;
  // Streamlit may recreate this iframe; keep only one active handler.
  if (doc.__practiceTimerShortcutCleanup) doc.__practiceTimerShortcutCleanup();
  const onKeyDown = event => {
    if (event.repeat || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return;
    if (event.key !== 'Pause' && event.code !== 'Pause') return;
    // Resolve the current button on each press, including after fragment reruns.
    // The tools control also works when the timer display is hidden.
    const button = doc.querySelector('.st-key-practice_timer_pause button:not(:disabled)')
      || doc.querySelector('.st-key-practice_timer_tools_pause button:not(:disabled)');
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    button.click();
  };
  const cleanup = () => {
    doc.removeEventListener('keydown', onKeyDown, true);
    if (doc.__practiceTimerShortcutCleanup === cleanup) {
      delete doc.__practiceTimerShortcutCleanup;
    }
    window.removeEventListener('pagehide', cleanup);
  };
  doc.addEventListener('keydown', onKeyDown, true);
  doc.__practiceTimerShortcutCleanup = cleanup;
  window.addEventListener('pagehide', cleanup);
})();
