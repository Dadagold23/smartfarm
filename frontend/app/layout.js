import "./globals.css";
import Shell from "../components/Shell";

export const metadata = {
  title: "ASIIS — AgroSmart Irrigation Intelligence",
  description: "Smart agricultural irrigation management platform",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
