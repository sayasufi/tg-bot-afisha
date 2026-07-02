import { createContext, useCallback, useContext, useState, ReactNode } from "react";

import { ApiError } from "./api";
import { useAuth } from "./auth";

/* ---------- Тосты ---------- */
type Toast = { id: number; text: string; kind: "ok" | "err" };
type ToastApi = { push: (text: string, kind?: "ok" | "err") => void };

const ToastCtx = createContext<ToastApi>({ push: () => {} });
export const useToast = () => useContext(ToastCtx);

let _tid = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "ok" | "err" = "err") => {
    const id = ++_tid;
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      {toasts.length > 0 && (
        <div className="toasts">
          {toasts.map((t) => (
            <div key={t.id} className={"toast toast--" + t.kind} role="status">
              {t.text}
            </div>
          ))}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

/* ---------- Обёртка мутаций ----------
   Ловит ошибку любой мутации (POST/PATCH/DELETE): показывает тост, а на 401/404
   (протухший токен → /v1/admin отвечает 404/401) чистит сессию и уводит на логин.
   Иначе такие кнопки просто молча не реагируют. */
export function useMutate() {
  const { push } = useToast();
  const { logout } = useAuth();

  return useCallback(
    async <T,>(fn: () => Promise<T>, okMsg?: string): Promise<T | undefined> => {
      try {
        const r = await fn();
        if (okMsg) push(okMsg, "ok");
        return r;
      } catch (e) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 404)) {
          push("сессия истекла — войдите заново", "err");
          logout();
          return undefined;
        }
        push(e instanceof Error ? e.message : "ошибка операции", "err");
        return undefined;
      }
    },
    [push, logout]
  );
}
