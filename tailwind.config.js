/** @type {import('tailwindcss').Config} */
// Used ONLY by bin/build-css.sh to compile web/static/css/tailwind.min.css.
// The committed .min.css is what the app serves — no Node required at runtime.
// Re-run the build script after adding any new Tailwind utility class to a
// template that isn't already present in the compiled CSS.
module.exports = {
  darkMode: 'class',
  content: ['./web/templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        ink:  { 900: '#0a0e1a', 800: '#12172a', 700: '#1e2541', 600: '#293354' },
        paper: { 50: '#fafafa', 100: '#f4f4f5', 200: '#e4e4e7', 300: '#d4d4d8' },
        gold: '#d4af37',
      },
    },
  },
};
