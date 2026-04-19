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

    window.moatlensToggleTheme = function () {
        current = current === 'dark' ? 'light' : 'dark';
        apply(current);
        try { localStorage.setItem(KEY, current); } catch (e) {}
        // Update toggle buttons if present
        document.querySelectorAll('[data-theme-toggle]').forEach((btn) => {
            btn.dataset.currentTheme = current;
        });
    };
    window.moatlensGetTheme = function () { return current; };
})();
