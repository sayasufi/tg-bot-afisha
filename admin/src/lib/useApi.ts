import { useCallback, useEffect, useState } from "react";

import { apiGet, ApiError } from "./api";
import { useAuth } from "./auth";

/** GET с опциональным поллингом. Любой 404/401 = сессия невалидна → выкидываем на логин. */
export function useApi<T = any>(path: string, pollMs?: number) {
  const { logout } = useAuth();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const d = await apiGet(path);
      // Стабилизируем ссылку: если поллинг вернул тот же JSON — не подменяем объект,
      // иначе downstream useMemo (filtered/sorted) пересортировывают массив на каждый
      // тик впустую. Дешёвый deep-equal через сериализацию (данные админки небольшие).
      setData((prev) => {
        try {
          if (prev != null && JSON.stringify(prev) === JSON.stringify(d)) return prev;
        } catch {
          /* циклы/несериализуемое — просто обновляем */
        }
        return d;
      });
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 401)) {
        logout();
        return;
      }
      setError(e instanceof Error ? e.message : "ошибка загрузки");
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    load();
    if (pollMs) {
      const id = setInterval(load, pollMs);
      return () => clearInterval(id);
    }
  }, [load, pollMs]);

  return { data, error, loading, reload: load };
}
