/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
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

