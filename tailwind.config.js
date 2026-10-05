/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  safelist: [
    {
      pattern: /^(bg|text|border)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-(50|100|200|300|400|500|600|700|800|900|950)$/,
    },
    {
      pattern: /^(bg|text|border)-(white|black|transparent)$/,
    }
  ],
  theme: {
    extend: {
      colors: {
        // Channels, not hex, so a view's theme can swap them at runtime and
        // opacity modifiers (`bg-brand-blue/5`) still work. Defaults: index.css.
        brand: {
          navy: 'rgb(var(--brand-navy) / <alpha-value>)',
          blue: 'rgb(var(--brand-blue) / <alpha-value>)',
          light: 'rgb(var(--brand-light) / <alpha-value>)',
        }
      }
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
  ],
}

