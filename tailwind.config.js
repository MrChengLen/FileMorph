/** @type {import('tailwindcss').Config}
 *
 * Design tokens — every value here is a *named role*, not a scale alias.
 * Authors should reach for the named token when one exists; raw utilities
 * remain available for genuinely one-off layout, but anything with a name
 * has exactly one answer. See app/templates/_components/README.md for the
 * macros that consume these tokens and the dynamic-class rule.
 */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // Primary brand — indigo. Existing.
        brand: { DEFAULT: '#6366f1', dark: '#4f46e5', light: '#818cf8' },
        // Surface tones — replace ad-hoc bg-gray-900 / bg-gray-900/50 / bg-gray-950.
        surface: { DEFAULT: '#0f1115', raised: '#171922', sunken: '#0a0c10' },
        // Ink (text) tones — replace text-gray-100 / -300 / -400 / -500 / -600 sprinkles.
        ink: { DEFAULT: '#e5e7eb', muted: '#9ca3af', faint: '#6b7280', dim: '#4b5563' },
        // Hairline border, single source of truth.
        hairline: '#1f2937',
      },
      spacing: {
        // Vertical rhythm between page-level <section> blocks.
        'section-y': '5rem',
        'section-sm': '3rem',
        // Canonical card inner padding.
        'card-pad-md': '1.5rem',
        'card-pad-lg': '2rem',
      },
      borderRadius: {
        // Every card surface.
        card: '1rem',
        // Every input / select / small button.
        control: '0.625rem',
        pill: '9999px',
      },
      fontSize: {
        // Semantic typography roles. Authors write text-h-page, not text-3xl.
        'h-page':  ['1.875rem', { lineHeight: '2.25rem', fontWeight: '700' }],
        'h-sect':  ['1.5rem',   { lineHeight: '2rem',    fontWeight: '700' }],
        'h-card':  ['1rem',     { lineHeight: '1.5rem',  fontWeight: '600' }],
        'eyebrow': ['0.75rem',  { lineHeight: '1rem',    letterSpacing: '0.08em', fontWeight: '600' }],
      },
      maxWidth: {
        'page': '64rem',
        'prose-narrow': '42rem',
      },
      boxShadow: {
        card: '0 1px 0 rgba(255,255,255,0.03), 0 8px 32px rgba(0,0,0,0.45)',
      },
    },
  },
  plugins: [],
};
