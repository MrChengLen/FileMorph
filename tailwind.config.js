/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#6366f1', dark: '#4f46e5', light: '#818cf8' }
      }
    }
  },
  plugins: [],
};
