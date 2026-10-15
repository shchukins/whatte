// Controlled DOM value only: consumers submit explicitly through the parent form.
document.querySelectorAll('[data-rpe-selector]').forEach(selector => {
    const form = selector.closest('form');
    const history = form?.querySelector('[data-rpe-history]');
    const compare = form?.querySelector('[data-rpe-compare]');
    let pending;
    async function loadHistory() {
        const selected = selector.querySelector('input:checked');
        if (!selected || !history || !compare) return;
        pending?.abort();
        const controller = new AbortController();
        pending = controller;
        history.hidden = false;
        history.textContent = 'Ищем похожие тренировки…';
        history.setAttribute('aria-busy', 'true');
        try {
            const url = new URL(compare.formAction);
            url.hash = '';
            url.searchParams.set('score', selected.value);
            url.searchParams.set('fragment', 'true');
            const response = await fetch(url, {signal: controller.signal, cache: 'no-store'});
            if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('history');
            const html = await response.text();
            if (!controller.signal.aborted) history.innerHTML = html;
        } catch (error) {
            if (!controller.signal.aborted) history.textContent = 'История временно недоступна. Можно сохранить выбор или повторить сравнение.';
        } finally {
            if (pending === controller) history.removeAttribute('aria-busy');
        }
    }
    selector.addEventListener('change', () => {
        const selected = selector.querySelector('input:checked');
        selector.querySelector('[data-rpe-value]').textContent = selected ? `${selected.value} / 10` : 'Не выбрано';
        loadHistory();
    });
    compare?.addEventListener('click', event => {
        if (!form.reportValidity()) return;
        event.preventDefault();
        loadHistory();
    });
});
