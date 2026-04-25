/**
 * Light / dark theme toggle with localStorage persistence.
 * Respects prefers-color-scheme on first visit.
 */
(function () {
    const KEY = 'moatlens-theme';
    const html = document.documentElement;

    function apply(theme) {
        if (theme === 'light') {
            html.classList.remove('dark');
        } else {
            html.classList.add('dark');
        }
    }

    // Initial: stored preference → OS preference → default dark
    let stored = null;
    try { stored = localStorage.getItem(KEY); } catch (e) {}
    let current = stored;
    if (!current) {
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        current = prefersDark ? 'dark' : 'light';
    }
    apply(current);

    function _sync_toggles() {
        // Keep all theme-toggle buttons' aria-pressed in sync with current theme.
        // `aria-pressed="true"` on the toggle means "dark mode is active" — lets
        // screen readers announce the state without relying on the sun/moon icon.
        document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
            btn.dataset.currentTheme = current;
            btn.setAttribute('aria-pressed', current === 'dark' ? 'true' : 'false');
        });
    }

    window.moatlensToggleTheme = function () {
        current = current === 'dark' ? 'light' : 'dark';
        apply(current);
        try { localStorage.setItem(KEY, current); } catch (e) {}
        _sync_toggles();
    };
    window.moatlensGetTheme = function () { return current; };

    // On first paint, sync aria-pressed too.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _sync_toggles);
    } else {
        _sync_toggles();
    }
})();
