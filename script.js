// Auto-hide flash messages after 4s
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.flash').forEach(el => {
        setTimeout(() => {
            el.style.transition = 'opacity .5s';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 500);
        }, 4000);
    });

    // Fill generated-date on statement page
    const genDate = document.getElementById('genDate');
    if (genDate) genDate.textContent = new Date().toLocaleString();

    // Uppercase account number fields
    document.querySelectorAll('input[name="account_number"], input[name="from_account"], input[name="to_account"]')
        .forEach(inp => inp.addEventListener('input', e => e.target.value = e.target.value.trim()));
});