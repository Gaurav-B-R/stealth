/* Navigation only: editorial news is rendered in HTML and makes no news API calls. */
(function () {
    'use strict';
    const year = document.getElementById('yr');
    if (year) year.textContent = new Date().getFullYear();
    document.querySelectorAll('.nav-links a[href="/news"]').forEach((link) => {
        link.setAttribute('aria-current', location.pathname.replace(/\/$/, '') === '/news' ? 'page' : 'true');
    });

    const toggle = document.getElementById('navToggle');
    const links = document.getElementById('navLinks');
    const products = document.getElementById('productsNav');
    const trigger = document.getElementById('productsNavTrigger');
    const setMenu = (open) => {
        if (!toggle || !links) return;
        links.classList.toggle('open', open);
        toggle.setAttribute('aria-expanded', String(open));
    };
    const setProducts = (open) => {
        if (!products || !trigger) return;
        products.classList.toggle('is-open', open);
        trigger.setAttribute('aria-expanded', String(open));
    };
    if (toggle && links) {
        toggle.addEventListener('click', () => setMenu(!links.classList.contains('open')));
        links.addEventListener('click', (event) => {
            if (event.target.closest('a')) { setMenu(false); setProducts(false); }
        });
    }
    if (products && trigger) trigger.addEventListener('click', () => setProducts(!products.classList.contains('is-open')));
    document.addEventListener('click', (event) => {
        if (links && toggle && !links.contains(event.target) && !toggle.contains(event.target)) setMenu(false);
        if (products && !products.contains(event.target)) setProducts(false);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape') return;
        if (links && links.classList.contains('open')) { setMenu(false); toggle.focus(); }
        if (products && products.classList.contains('is-open')) { setProducts(false); trigger.focus(); }
    });
})();
