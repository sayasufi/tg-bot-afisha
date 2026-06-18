// A tiny global toast: one transient confirmation at a time ("Добавлено в избранное",
// "Напомним перед началом"). Pub/sub so any component can fire one with no prop drilling;
// a single <Toaster> (mounted in App) renders the current message.
export type ToastTone = "good" | "muted";
export type ToastIcon = "heart" | "bell" | "share";
export type ToastMsg = { id: number; text: string; tone: ToastTone; icon?: ToastIcon };

type Listener = (t: ToastMsg) => void;

let listeners: Listener[] = [];
let counter = 0;

export function showToast(text: string, opts?: { tone?: ToastTone; icon?: ToastIcon }): void {
  counter += 1;
  const msg: ToastMsg = { id: counter, text, tone: opts?.tone ?? "good", icon: opts?.icon };
  for (const l of listeners) l(msg);
}

export function subscribeToast(l: Listener): () => void {
  listeners.push(l);
  return () => {
    listeners = listeners.filter((x) => x !== l);
  };
}
