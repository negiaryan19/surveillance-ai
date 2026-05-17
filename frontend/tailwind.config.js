/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'cyber-bg': '#090A0F',
        'cyber-panel': '#0D1117',
        'neon-green': '#00FFA3',
        'neon-red': '#FF4A4A',
        'cyber-border': '#1F2430',
        'cyber-text': '#8B949E'
      },
      fontFamily: {
        mono: ['"Courier New"', 'Courier', 'monospace'],
      }
    },
  },
  plugins: [],
}