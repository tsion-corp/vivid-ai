/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  presets: [require("nativewind/preset")],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: { DEFAULT: "#ffffff", dark: "#0b0b0f" },
        foreground: { DEFAULT: "#0b0b0f", dark: "#ececf1" },
        card: { DEFAULT: "#f6f6f8", dark: "#16161c" },
        muted: { DEFAULT: "#6b6b76", dark: "#9a9aa6" },
        border: { DEFAULT: "#e6e6ea", dark: "#26262e" },
        primary: { DEFAULT: "#e8590c", foreground: "#ffffff" },
      },
    },
  },
  plugins: [],
};
