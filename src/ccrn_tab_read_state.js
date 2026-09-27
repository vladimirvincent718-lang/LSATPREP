(function () {
    'use strict';
    const config = __CCRN_TAB_CONFIG__;
    const P = window.parent;
    const doc = P.document;
    if (P._sfCcrnReadCleanup) P._sfCcrnReadCleanup();
    const key = 'sf-ccrn-read-v1:' + config.user + ':' + config.course;
    P._sfCcrnReadCache = P._sfCcrnReadCache || {};
    let state = P._sfCcrnReadCache[key] || {};
    try { state = JSON.parse(P.localStorage.getItem(key) || 'null') || state; } catch (_) {}
    if (!state || typeof state !== 'object' || Array.isArray(state)) state = {};
    function save() {
        P._sfCcrnReadCache[key] = state;
        try { P.localStorage.setItem(key, JSON.stringify(state)); } catch (_) {}
    }
    // New batches need attention; editing or importing existing batches does not reset reads.
    config.sections.forEach(section => {
        const previous = state[section.id];
        const added = !previous || !Array.isArray(previous.batches) ||
            section.batches.some(id => !previous.batches.includes(id));
        state[section.id] = {
            batches: section.batches,
            unread: added ? section.batches.length > 0 : !!previous.unread
        };
    });
    save();
    function sectionFor(tab) {
        if (!tab) return null;
        return config.sections.find(s => (tab.textContent || '').trim() === s.label);
    }
    function setRead(section, unread) {
        state[section.id].unread = unread;
        save();
        paint();
    }
    function paint() {
        doc.querySelectorAll('[role="tab"]').forEach(tab => {
            const broken = (tab.textContent || '').includes('⚠') || (tab.textContent || '').includes('need fixes');
            if (tab.classList.contains('sf-ccrn-broken-tab') !== broken)
                tab.classList.toggle('sf-ccrn-broken-tab', broken);
        });
        doc.querySelectorAll('[role="tablist"]').forEach(list => {
            const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
            if (!tabs.some(sectionFor)) return;
            tabs.forEach(tab => {
                const section = sectionFor(tab);
                if (!section) return;
                const unread = state[section.id].unread;
                if (tab.classList.contains('sf-ccrn-pending-tab') !== unread)
                    tab.classList.toggle('sf-ccrn-pending-tab', unread);
                const title = unread ? 'Unread — open this section to mark it read' : 'Read — use Mark unread to highlight again';
                if (tab.getAttribute('title') !== title) tab.setAttribute('title', title);
            });
            let button = list.parentElement.querySelector(':scope > .sf-ccrn-mark-unread');
            if (!button) {
                button = doc.createElement('button');
                button.type = 'button';
                button.className = 'sf-ccrn-mark-unread';
                button.textContent = 'Mark unread';
                list.insertAdjacentElement('afterend', button);
            }
            const selected = sectionFor(tabs.find(t => t.getAttribute('aria-selected') === 'true'));
            button.disabled = !selected || state[selected.id].unread;
            const label = selected ? 'Mark ' + selected.label.replace(/\s+·.*$/, '') + ' unread' : 'Mark unread';
            if (button.getAttribute('aria-label') !== label) button.setAttribute('aria-label', label);
        });
    }
    function click(event) {
        const navigation = event.target.closest('a.sf-import-step, a.sf-workflow-jump');
        if (navigation) {
            const destination = doc.getElementById((navigation.getAttribute('href') || '').slice(1));
            if (destination) {
                event.preventDefault();
                // Open every containing expander before scrolling to a stage.
                const expanders = [];
                for (let parent = destination.closest('details'); parent;
                     parent = parent.parentElement && parent.parentElement.closest('details')) {
                    expanders.unshift(parent);
                }
                expanders.forEach(expander => {
                    if (!expander.open) expander.querySelector('summary').click();
                });
                destination.scrollIntoView({behavior: 'smooth', block: 'start'});
            }
            return;
        }
        const button = event.target.closest('.sf-ccrn-mark-unread');
        if (button) {
            const list = button.previousElementSibling;
            const section = sectionFor(list.querySelector('[role="tab"][aria-selected="true"]'));
            if (section) setRead(section, true);
            return;
        }
        const section = sectionFor(event.target.closest('[role="tab"]'));
        if (section) setRead(section, false);
    }
    function edit(event) {
        if (!event.target.matches('textarea, input, [contenteditable="true"]')) return;
        const panel = event.target.closest('[role="tabpanel"]');
        const section = panel && sectionFor(doc.getElementById(panel.getAttribute('aria-labelledby')));
        if (section) setRead(section, false);
    }
    function keyboard(event) {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        const list = event.target.closest('[role="tablist"]');
        if (list) P.setTimeout(() => {
            const section = sectionFor(list.querySelector('[role="tab"][aria-selected="true"]'));
            if (section) setRead(section, false);
        }, 0);
    }
    function highlightReview(event) {
        const detail = event.detail || {};
        if (detail.user !== config.user || detail.course !== config.course || !Array.isArray(detail.ids)) return;
        detail.ids.forEach(id => { if (state[id]) state[id].unread = true; });
        save(); paint();
    }
    doc.addEventListener('sf-import-highlight-review', highlightReview);
    doc.addEventListener('click', click);
    doc.addEventListener('focusin', edit);
    doc.addEventListener('input', edit);
    doc.addEventListener('keydown', keyboard);
    const observer = new MutationObserver(paint);
    observer.observe(doc.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['aria-selected', 'class']});
    P._sfCcrnReadCleanup = () => {
        observer.disconnect();
        doc.removeEventListener('click', click);
        doc.removeEventListener('focusin', edit);
        doc.removeEventListener('input', edit);
        doc.removeEventListener('keydown', keyboard);
        doc.removeEventListener('sf-import-highlight-review', highlightReview);
    };
    paint();
})();
