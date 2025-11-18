import { Accessor, createEffect, Setter } from "solid-js";

export function bindingInputOnChange(
	element: HTMLInputElement,
	accessor: () => [Accessor<string>, Setter<string>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) =>
		set((event.currentTarget as HTMLInputElement).value),
	);
	createEffect(() => (element.value = s()));
}

declare module "solid-js" {
	namespace JSX {
		interface DirectiveFunctions {
			bindingInputOnChange: typeof bindingInputOnChange;
		}
	}
}
