// Controlled DOM value only: consumers submit explicitly through the parent form.
document.querySelectorAll('[data-rpe-selector]').forEach(selector => {
    selector.addEventListener('change', () => {
        const selected = selector.querySelector('input:checked');
        selector.querySelector('[data-rpe-value]').textContent = selected ? `${selected.value} / 10` : 'Не выбрано';
    });
});
