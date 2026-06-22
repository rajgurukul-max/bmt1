/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx}",
    "./src/components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        pitch: {
          DEFAULT: "#0E1F14", // deep pitch-at-night background
          surface: "#16291C", // card surface
          border: "#1E3324", // hairline borders
          borderlight: "#2C4A33",
        },
        turf: {
          DEFAULT: "#8BC34A", // primary accent - floodlit grass green
          light: "#9BCF5E",
        },
        chalk: "#F4F7ED", // floodlight white text
        muted: "#9FB0A3",
        dim: "#5C7066",
        amber: "#E8A33D",
        danger: "#E5484D",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
