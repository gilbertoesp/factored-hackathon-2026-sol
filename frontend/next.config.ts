import type { NextConfig } from "next";

const config: NextConfig = {
	// Self-contained server in .next/standalone: the runtime image copies only
	// that folder, without node_modules from the build stage.
	output: "standalone",
	poweredByHeader: false,
};

export default config;
