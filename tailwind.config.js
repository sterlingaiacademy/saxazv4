/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./static/**/*.js",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Outfit', 'sans-serif'],
        logo: ['"Varela Round"', 'sans-serif'],
      },
      colors: {
        saxaz: {
          gold:  '#F4AA00',
          dark:  '#1e1e1e',
          light: '#f9fafb',
          grey:  '#e5e7eb',
        }
      },
      keyframes: {
        fadeInUp: {
          '0%':   { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        }
      },
      animation: {
        'fade-in-up': 'fadeInUp 0.6s ease-out forwards',
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        saxazlight: {
          "primary":         "#F4AA00",
          "primary-content": "#1e1e1e",
          "secondary":       "#3B82F6",
          "accent":          "#10B981",
          "neutral":         "#3D4451",
          "base-100":        "#ffffff",
          "base-200":        "#f3f4f6",
          "base-300":        "#e5e7eb",
          "base-content":    "#1f2937",
          "info":            "#3ABFF8",
          "success":         "#36D399",
          "warning":         "#FBBD23",
          "error":           "#F87272",
        },
      },
      {
        saxazdark: {
          "primary":         "#F4AA00",
          "primary-content": "#1e1e1e",
          "secondary":       "#3B82F6",
          "accent":          "#10B981",
          "neutral":         "#3D4451",
          "base-100":        "#1d232a",
          "base-200":        "#191e24",
          "base-300":        "#15191e",
          "base-content":    "#a6adbb",
          "info":            "#3ABFF8",
          "success":         "#36D399",
          "warning":         "#FBBD23",
          "error":           "#F87272",
        },
      },
      "light",
      "dark",
      "winter",
      "dracula",
    ],
  },
}
