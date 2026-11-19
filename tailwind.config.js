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
        // Primary brand — indigo. DEFAULT is the logo/icon/focus-ring colour;
        // text in brand colour uses `light`, white text sits on `dark`
        // (hover `deep`) — each at least 4.5:1 (WCAG AA), pinned by
        // tests/test_public_claims.py.
        brand: { DEFAULT: '#6366f1', dark: '#4f46e5', deep: '#4338ca', light: '#818cf8' },
        // Surface tones — replace ad-hoc bg-gray-900 / bg-gray-900/50 / bg-gray-950.
        // page is the body background, the darkest tone.
        surface: { DEFAULT: '#0f1115', raised: '#171922', sunken: '#0a0c10', page: '#030712' },
        // Ink (text) tones — replace text-white / -gray-100 / -300 / -400 / -500 / -600 sprinkles.
        // strong is the brightest (body default, headings, hover), soft the one
        // below ink. faint is the palest readable text: ≥ 4.5:1 on every dark
        // surface up to gray-800. dim is for disabled controls and decorative icons only.
        ink: { DEFAULT: '#e5e7eb', strong: '#ffffff', soft: '#d1d5db', muted: '#9ca3af', faint: '#8b929e', dim: '#4b5563' },
        // Borders, single source of truth: hairline between areas, strong around controls.
        hairline: { DEFAULT: '#1f2937', strong: '#374151' },
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
        // h-page grows with the screen: 26 px on a phone, about 30 px on a laptop
        // (the tool stays in the first screen at 1280 × 600), 36 px from 2000 px.
        // The rem parts keep it growing with the reader's zoom (WCAG 1.4.4).
        'h-page':  ['clamp(1.625rem, 1.25rem + 0.8vw, 2.25rem)', { lineHeight: '1.15', fontWeight: '700' }],
        'h-sect':  ['1.5rem',   { lineHeight: '2rem',    fontWeight: '700' }],
        'h-card':  ['1rem',     { lineHeight: '1.5rem',  fontWeight: '600' }],
        'eyebrow': ['0.75rem',  { lineHeight: '1rem',    letterSpacing: '0.08em', fontWeight: '600' }],
      },
      // The page frame and the column widths inside it. Header, every <main>
      // (the page() macro) and the footer share `page`, so their edges line up
      // on every screen; 70rem (1120 px) is the frame width of the target
      // design. A page's content column is one of the other three.
      maxWidth: {
        'page': '70rem',
        'wide': '56rem',
        'prose-narrow': '42rem',
        'form': '28rem',
      },
      boxShadow: {
        card: '0 1px 0 rgba(255,255,255,0.03), 0 8px 32px rgba(0,0,0,0.45)',
      },
    },
  },
  plugins: [],
};
