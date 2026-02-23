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
        qualcomm: {
          navy: '#001E3C',
          blue: '#007BFF',
          light: '#F8F9FA',
        }
      }
    },
  },
  plugins: [],
}

