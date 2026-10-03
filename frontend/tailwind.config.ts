import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // "Night Desk" palette — ink surfaces, amber signal, P/L semantics.
        ink: {
          950: "#06070a",
          900: "#0b0d12",
          850: "#10131a",
          800: "#151922",
          700: "#1e2330",
          600: "#2a3142",
        },
        paper: {
          DEFAULT: "#ece6d9",
          dim: "#a9a397",
          mute: "#6d6a63",
        },
        amber: {
          glow: "#ffb547",
          deep: "#c9821c",
        },
        gain: "#3ddc97",
        loss: "#ff5c6c",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        display: ["var(--font-display)", "ui-serif", "Georgia", "serif"],
      },
      keyframes: {
        rise: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        bars: {
          "0%, 100%": { transform: "scaleY(0.35)" },
          "50%": { transform: "scaleY(1)" },
        },
      },
      animation: {
        rise: "rise .45s cubic-bezier(.2,.7,.2,1) backwards",
        bars: "bars 1s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;
