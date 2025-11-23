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

export function bindingInputOnInput(
	element: HTMLInputElement,
	accessor: () => [Accessor<string>, Setter<string>],
) {
	const [s, set] = accessor();
	element.addEventListener("input", (event) =>
		set((event.currentTarget as HTMLInputElement).value),
	);
	createEffect(() => (element.value = s()));
}

export function bindingTextareaOnChange(
	element: HTMLTextAreaElement,
	accessor: () => [Accessor<string>, Setter<string>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) =>
		set((event.currentTarget as HTMLTextAreaElement).value),
	);
	createEffect(() => (element.value = s()));
}

export function bindingInputNumberOnChange(
	element: HTMLInputElement,
	accessor: () => [Accessor<number>, Setter<number>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) =>
		set(+(event.currentTarget as HTMLInputElement).value),
	);
	createEffect(() => (element.value = s().toString()));
}

export function bindingInputPositiveNumberOnChange(
	element: HTMLInputElement,
	accessor: () => [Accessor<number>, Setter<number>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) => {
		const elementValue = +(event.currentTarget as HTMLInputElement).value;
		if (elementValue > 0) {
			set(elementValue);
		}
	});
	createEffect(() => (element.value = s().toString()));
}

export function bindingInputPositiveNumberOrZeroOnChange(
	element: HTMLInputElement,
	accessor: () => [Accessor<number>, Setter<number>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) => {
		const elementValue = +(event.currentTarget as HTMLInputElement).value;
		if (elementValue >= 0) {
			set(elementValue);
		}
	});
	createEffect(() => (element.value = s().toString()));
}

export function bindingInputChecked(
	element: HTMLInputElement,
	accessor: () => [Accessor<boolean>, Setter<boolean>],
) {
	const [s, set] = accessor();
	element.addEventListener("change", (event) => {
		const elementChecked = (event.currentTarget as HTMLInputElement).checked;
		set(elementChecked);
	});
	createEffect(() => (element.checked = s()));
}

declare module "solid-js" {
	namespace JSX {
		interface DirectiveFunctions {
			bindingInputOnChange: typeof bindingInputOnChange;
			bindingInputOnInput: typeof bindingInputOnInput;
			bindingTextareaOnChange: typeof bindingTextareaOnChange;
			bindingInputNumberOnChange: typeof bindingInputNumberOnChange;
			bindingInputPositiveNumberOnChange: typeof bindingInputPositiveNumberOnChange;
			bindingInputPositiveNumberOrZeroOnChange: typeof bindingInputPositiveNumberOrZeroOnChange;
			bindingInputChecked: typeof bindingInputChecked;
		}
	}
}
