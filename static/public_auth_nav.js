/* Keep static marketing-page navigation consistent with the real cookie session.
   These pages do not load the full B2C app, so they need a small, fail-closed check. */
(function () {
    'use strict';

    let authCheckGeneration = 0;

    function discoverAuthLinks() {
        document.querySelectorAll('.nav-links a[href="/login"]').forEach((link) => {
            link.dataset.publicAuthRole = 'login';
            link.dataset.publicAuthText = link.textContent.trim() || 'Login';
        });
        document.querySelectorAll('.nav-links a[href="/register"]').forEach((link) => {
            link.dataset.publicAuthRole = 'register';
        });
    }

    function renderLoggedOut() {
        document.querySelectorAll('[data-public-auth-role="login"]').forEach((link) => {
            link.href = '/login';
            link.textContent = link.dataset.publicAuthText || 'Login';
        });
        document.querySelectorAll('[data-public-auth-role="register"]').forEach((link) => {
            link.hidden = false;
        });
    }

    function renderLoggedIn() {
        document.querySelectorAll('[data-public-auth-role="login"]').forEach((link) => {
            link.href = '/dashboard';
            link.textContent = 'Dashboard';
        });
        document.querySelectorAll('[data-public-auth-role="register"]').forEach((link) => {
            link.hidden = true;
        });
    }

    async function syncPublicAuthNavigation() {
        const generation = ++authCheckGeneration;
        discoverAuthLinks();
        // Fail closed while the request is in flight: never preserve a restored account UI.
        renderLoggedOut();
        try {
            const response = await fetch('/api/auth/me', {
                credentials: 'same-origin',
                cache: 'no-store',
                headers: { Accept: 'application/json' }
            });
            if (generation !== authCheckGeneration) return;
            if (response.ok) renderLoggedIn();
        } catch (error) {
            // Network/auth failures intentionally leave the anonymous navigation in place.
        }
    }

    syncPublicAuthNavigation();
    window.addEventListener('pageshow', (event) => {
        if (event.persisted) syncPublicAuthNavigation();
    });
})();
