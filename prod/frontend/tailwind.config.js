/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        background: 'hsl(222 47% 11%)',
        foreground: 'hsl(210 40% 98%)',
        card: 'hsl(222 47% 14%)',
        'card-foreground': 'hsl(210 40% 98%)',
        primary: 'hsl(217 91% 60%)',
        secondary: 'hsl(215 28% 17%)',
        muted: 'hsl(215 28% 17%)',
        'muted-foreground': 'hsl(215 20% 65%)',
        destructive: 'hsl(0 63% 31%)',
        success: 'hsl(142 76% 36%)',
        warning: 'hsl(45 93% 47%)',
        border: 'hsl(215 28% 20%)',
      },
    },
  },
  plugins: [],
}
