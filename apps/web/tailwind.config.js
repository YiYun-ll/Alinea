/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#273449',
        accent: '#5675A8',
        paper: '#F6F7F9',
        amber: '#D98B27',
        danger: '#C14F4F',
        pass: '#278267',
      },
      fontFamily: {
        sans: ['Noto Sans SC', 'Source Han Sans SC', 'Microsoft YaHei', 'sans-serif'],
        display: ['Noto Serif SC', 'Source Han Serif SC', 'SimSun', 'serif'],
      },
    },
  },
  plugins: [],
}
