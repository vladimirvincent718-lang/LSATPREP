(function () {
    'use strict';
    const config = __IMPORT_TAB_CONFIG__;
    const P = window.parent, doc = P.document;
    if (P._sfImportToolbarCleanup) P._sfImportToolbarCleanup();
    const valid = new Set(config.sections.map(s => s.id));
    P._sfImportTabSelections = P._sfImportTabSelections || {};
    const picked = new Set((P._sfImportTabSelections[config.course] || []).filter(id => valid.has(id)));
    let anchor = null;
    const reviews = config.reviews || [];
    const scope = config.user + ':' + config.course;
    P._sfImportReviewFilters = P._sfImportReviewFilters || {};
    let reviewId = P._sfImportReviewFilters[scope] || '';
    if (!reviews.some(r => r.id === reviewId)) reviewId = '';
    P._sfImportReviewViews = P._sfImportReviewViews || {};
    let reviewView = P._sfImportReviewViews[scope] || 'inside';
    if (!['all', 'inside', 'outside'].includes(reviewView)) reviewView = 'inside';
    const shownSections = () => {
        const review = reviews.find(r => r.id === reviewId);
        if (!review || reviewView === 'all') return config.sections;
        return config.sections.filter(s => review.ids.includes(s.id) === (reviewView === 'inside'));
    };
    function restrictSelection() {
        const shown = new Set(shownSections().map(s => s.id));
        [...picked].forEach(id => { if (!shown.has(id)) picked.delete(id); });
        save();
    }
    restrictSelection();
    const sectionFor = tab => tab && config.sections.find(s => (tab.textContent || '').trim() === s.label);
    function save() { P._sfImportTabSelections[config.course] = [...picked]; }
    function form() {
        const input = doc.querySelector('input[aria-label="Import tab deletion selection"]');
        return input && input.closest('[data-testid="stForm"]');
    }
    function submit(ids, action = 'delete') {
        const allowed = new Set((action === 'restore' ? config.removed : shownSections()).map(s => s.id));
        ids = ids.filter(id => allowed.has(id));
        if (!ids.length) return;
        const owner = form();
        if (!owner) return;
        const input = owner.querySelector('input[aria-label="Import tab deletion selection"]');
        const button = Array.from(owner.querySelectorAll('button')).find(b => b.textContent.trim() === 'Apply import tab deletion');
        if (!input || !button) return;
        Object.getOwnPropertyDescriptor(P.HTMLInputElement.prototype, 'value').set.call(input, JSON.stringify({action, ids}));
        input.dispatchEvent(new P.Event('input', {bubbles: true}));
        input.dispatchEvent(new P.Event('change', {bubbles: true}));
        // Submit the existing Streamlit form, including every unsaved paste box.
        P.setTimeout(() => { button.click(); }, 80);
    }
    function makeButton(label, action) {
        const button = doc.createElement('button');
        button.type = 'button'; button.className = 'sf-import-tab-action';
        button.textContent = label; button.addEventListener('click', action);
        return button;
    }
    function highlightReview() {
        const review = reviews.find(r => r.id === reviewId);
        if (!review) return;
        doc.dispatchEvent(new P.CustomEvent('sf-import-highlight-review', {
            detail: {user: config.user, course: config.course, ids: review.ids}
        }));
    }
    function paint() {
        const owner = form();
        if (!owner) return;
        const list = Array.from(owner.querySelectorAll('[role="tablist"]')).find(l => Array.from(l.querySelectorAll('[role="tab"]')).some(sectionFor));
        if (!list) return;
        const mark = list.parentElement.querySelector(':scope > .sf-ccrn-mark-unread');
        if (!mark) return;
        const tabs = Array.from(list.querySelectorAll('[role="tab"]'));
        let filter = list.parentElement.querySelector(':scope > .sf-import-review-filter');
        if (!filter) {
            filter = doc.createElement('div'); filter.className = 'sf-import-review-filter';
            const label = doc.createElement('label'); label.textContent = 'Show tabs for review: ';
            const select = doc.createElement('select'); select.setAttribute('aria-label', 'Show tabs for review');
            [{id: '', name: 'All modules'}, ...reviews].forEach(review => {
                const option = doc.createElement('option'); option.value = review.id; option.textContent = review.name;
                select.appendChild(option);
            });
            select.value = reviewId;
            select.addEventListener('change', () => {
                reviewId = select.value; P._sfImportReviewFilters[scope] = reviewId;
                picked.clear(); anchor = null; save();
                list.parentElement.querySelector('.sf-import-bulk-menu')?.remove();
                list.parentElement.querySelector('.sf-import-delete-selected')?.setAttribute('aria-expanded', 'false');
                paint();
                highlightReview();
                // React may finish focusing the auto-opened panel after click.
                // Apply the reset after that read notification as well.
                P.setTimeout(highlightReview, 0);
            });
            // Native selects do not emit change when the same option is chosen.
            // Reopening the review picker also restores that review's yellow tabs.
            select.addEventListener('pointerdown', highlightReview);
            select.addEventListener('keydown', event => {
                if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(event.key)) highlightReview();
            });
            label.appendChild(select); filter.appendChild(label);
            const viewLabel = doc.createElement('label'); viewLabel.textContent = 'Show: ';
            const view = doc.createElement('select'); view.setAttribute('aria-label', 'Review membership');
            [['all', 'All modules'], ['inside', 'In this review'], ['outside', 'Outside this review']].forEach(([value, text]) => {
                const option = doc.createElement('option'); option.value = value; option.textContent = text;
                view.appendChild(option);
            });
            view.addEventListener('change', () => {
                reviewView = view.value; P._sfImportReviewViews[scope] = reviewView;
                picked.clear(); anchor = null; save();
                list.parentElement.querySelector('.sf-import-bulk-menu')?.remove();
                list.parentElement.querySelector('.sf-import-delete-selected')?.setAttribute('aria-expanded', 'false');
                paint();
            });
            viewLabel.appendChild(view); filter.appendChild(viewLabel);
            filter.appendChild(makeButton('Select all shown tabs', () => {
                list.parentElement.querySelector('.sf-import-bulk-menu')?.remove();
                list.parentElement.querySelector('.sf-import-delete-selected')?.setAttribute('aria-expanded', 'false');
                picked.clear(); shownSections().forEach(s => picked.add(s.id)); save(); paint();
            }));
            filter.appendChild(makeButton('Invert selection', () => {
                shownSections().forEach(s => picked.has(s.id) ? picked.delete(s.id) : picked.add(s.id));
                anchor = null; save();
                list.parentElement.querySelector('.sf-import-bulk-menu')?.remove();
                list.parentElement.querySelector('.sf-import-delete-selected')?.setAttribute('aria-expanded', 'false');
                paint();
            }));
            const outside = makeButton('Select outside review', () => {
                if (!reviewId) return;
                reviewView = 'outside'; P._sfImportReviewViews[scope] = reviewView;
                picked.clear(); shownSections().forEach(s => picked.add(s.id));
                anchor = null; save();
                list.parentElement.querySelector('.sf-import-bulk-menu')?.remove();
                list.parentElement.querySelector('.sf-import-delete-selected')?.setAttribute('aria-expanded', 'false');
                paint();
            });
            outside.classList.add('sf-import-select-outside'); filter.appendChild(outside);
            const count = doc.createElement('span'); count.className = 'sf-import-review-count'; count.setAttribute('role', 'status');
            filter.appendChild(count); list.insertAdjacentElement('beforebegin', filter);
        }
        const view = filter.querySelector('[aria-label="Review membership"]');
        view.value = reviewId ? reviewView : 'all'; view.disabled = !reviewId;
        filter.querySelector('.sf-import-select-outside').disabled = !reviewId;
        const shown = new Set(shownSections().map(s => s.id));
        const countText = shown.size ? `${shown.size} tabs shown · ${config.sections.length - shown.size} hidden · ${picked.size} selected`
            : `No tabs match this filter (${reviewView === 'outside' ? 'outside' : 'in'} this review). Choose All modules to see every tab.`;
        const count = filter.querySelector('.sf-import-review-count');
        if (count.textContent !== countText) count.textContent = countText;
        tabs.forEach(tab => {
            const section = sectionFor(tab);
            const excluded = !!section && !shown.has(section.id);
            if (excluded) tab.style.setProperty('display', 'none', 'important');
            else tab.style.removeProperty('display');
            const panel = doc.getElementById(tab.getAttribute('aria-controls'));
            if (panel) {
                if (excluded) panel.style.setProperty('display', 'none', 'important');
                else panel.style.removeProperty('display');
            }
            const selected = !!section && picked.has(section.id);
            if (tab.classList.contains('sf-import-tab-selected') !== selected)
                tab.classList.toggle('sf-import-tab-selected', selected);
        });
        const active = tabs.find(t => t.getAttribute('aria-selected') === 'true');
        if (active && !shown.has(sectionFor(active)?.id) && shown.size) {
            const first = tabs.find(t => shown.has(sectionFor(t)?.id));
            // Changing the active tab must not change the bulk selection.
            switchingTab = true; first.click(); switchingTab = false;
        }
        let direct = list.parentElement.querySelector(':scope > .sf-import-delete-selected');
        if (!direct) {
            const bulk = makeButton('Delete ▾', () => {
                let menu = list.parentElement.querySelector(':scope > .sf-import-bulk-menu');
                if (menu) { menu.remove(); bulk.setAttribute('aria-expanded', 'false'); return; }
                menu = doc.createElement('div'); menu.className = 'sf-import-bulk-menu';
                const showList = (sections, action) => {
                menu.replaceChildren();
                const text = doc.createElement('p');
                text.textContent = action === 'restore' ? 'Select deleted tabs to restore.' : 'Select tabs to delete. Questions and saved batches are kept.';
                menu.appendChild(text);
                if (!sections.length) text.textContent = action === 'restore' ? 'No deleted tabs for this course.' : 'No tabs match this review.';
                const choices = doc.createElement('div'); choices.className = 'sf-import-bulk-list';
                sections.forEach(section => {
                    const label = doc.createElement('label'), checkbox = doc.createElement('input');
                    checkbox.type = 'checkbox'; checkbox.value = section.id;
                    checkbox.checked = action === 'delete' && picked.has(section.id);
                    label.appendChild(checkbox); label.appendChild(doc.createTextNode(section.name));
                    choices.appendChild(label);
                });
                menu.appendChild(makeButton('Select all', () => choices.querySelectorAll('input').forEach(c => { c.checked = true; })));
                menu.appendChild(makeButton('Clear', () => choices.querySelectorAll('input').forEach(c => { c.checked = false; })));
                menu.appendChild(choices);
                menu.appendChild(makeButton(action === 'restore' ? 'Restore selected tabs' : 'Delete selected tabs', () => submit(Array.from(choices.querySelectorAll('input:checked')).map(c => c.value), action)));
                menu.appendChild(makeButton('Cancel', () => { menu.remove(); bulk.setAttribute('aria-expanded', 'false'); }));
                };
                const current = sectionFor(tabs.find(t => t.getAttribute('aria-selected') === 'true'));
                const ids = picked.size ? [...picked] : current && shown.has(current.id) ? [current.id] : [];
                menu.appendChild(makeButton('Delete selected tabs (' + ids.length + ')', () => submit(ids)));
                menu.appendChild(makeButton('Delete in bulk…', () => showList(shownSections(), 'delete')));
                menu.appendChild(makeButton('Restore deleted tabs…', () => showList(config.removed, 'restore')));
                bulk.insertAdjacentElement('afterend', menu);
                bulk.setAttribute('aria-expanded', 'true');
            });
            bulk.classList.add('sf-import-delete-selected'); bulk.setAttribute('aria-expanded', 'false');
            mark.insertAdjacentElement('afterend', bulk);
        }
    }
    let switchingTab = false;
    function click(event) {
        if (switchingTab) return;
        const tab = event.target.closest('[role="tab"]'), owner = form();
        const section = sectionFor(tab);
        if (!owner || !section || !owner.contains(tab)) return;
        if (event.shiftKey && anchor) {
            const ids = shownSections().map(s => s.id), a = ids.indexOf(anchor), b = ids.indexOf(section.id);
            ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(id => picked.add(id));
        } else if (event.ctrlKey || event.metaKey) {
            if (!picked.size) {
                const current = sectionFor(owner.querySelector('[role="tab"][aria-selected="true"]'));
                if (current && current.id !== section.id) picked.add(current.id);
            }
            picked.has(section.id) ? picked.delete(section.id) : picked.add(section.id);
            anchor = section.id;
        } else { picked.clear(); picked.add(section.id); anchor = section.id; }
        save();
        const menu = owner.querySelector('.sf-import-bulk-menu');
        if (menu) menu.remove();
        const toggle = owner.querySelector('.sf-import-delete-selected');
        if (toggle) toggle.setAttribute('aria-expanded', 'false');
        paint();
    }
    doc.addEventListener('click', click, true);
    const observer = new MutationObserver(paint);
    observer.observe(doc.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['aria-selected']});
    P._sfImportToolbarCleanup = () => {
        observer.disconnect(); doc.removeEventListener('click', click, true);
        doc.querySelectorAll('.sf-import-review-filter, .sf-import-delete-selected, .sf-import-delete-bulk, .sf-import-bulk-menu').forEach(e => e.remove());
        const owner = form();
        if (owner) owner.querySelectorAll('[role="tab"], [role="tabpanel"]').forEach(e => { e.style.display = ''; });
    };
    paint();
})();
