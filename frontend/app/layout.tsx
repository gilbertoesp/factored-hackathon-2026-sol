import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
	title: "Agente de reclamos",
	description:
		"Convierte un cargo no reconocido en un reclamo verificado sobre la transacción exacta.",
};

export const viewport: Viewport = {
	width: "device-width",
	initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
	return (
		<html lang="es">
			<body>{children}</body>
		</html>
	);
}
