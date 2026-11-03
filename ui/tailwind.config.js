/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          '"Be Vietnam Pro"',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          'sans-serif',
        ],
      },
      colors: {
        agri: {
          50: '#f2fbf5',
          100: '#e1f6e8',
          200: '#c3ecd2',
          600: '#16794b',
          700: '#11613c',
          800: '#0d4d30',
          900: '#093823',
        },
        warm: {
          bg: 'var(--color-bg-warm)',
          surface: 'var(--color-surface)',
          selected: 'var(--color-surface-selected)',
          text: 'var(--color-text-primary)',
          muted: 'var(--color-text-secondary)',
          primary: 'var(--color-primary-green)',
          accent: 'var(--color-accent-orange)',
        },
      },
    },
  },
  plugins: [],
};


