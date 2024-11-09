import { fileURLToPath } from "url";
import { defineConfig } from "vite";
import solidPlugin from "vite-plugin-solid";
import devtools from "solid-devtools/vite";

export default defineConfig({
	base: "/thrimbletrimmer/",
	plugins: [devtools(), solidPlugin()],
	server: {
		port: 3000,
	},
	build: {
		target: "esnext",
		// minify: false, // Uncomment this line if you need to debug unminified code
		rollupOptions: {
			input: {
				index: fileURLToPath(new URL("index.html", import.meta.url)),
				edit: fileURLToPath(new URL("edit.html", import.meta.url)),
				utils: fileURLToPath(new URL("utils.html", import.meta.url)),
				thumbnails: fileURLToPath(new URL("thumbnails.html", import.meta.url)),
			},
		},
	},
});
