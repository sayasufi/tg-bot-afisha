import { useState } from "react";
import { createPortal } from "react-dom";

import { suggestEvent, uploadSuggestImage } from "../../api/suggest";
import { IconClose } from "../../lib/icons";
import { hapticNotify } from "../../lib/telegram";

const CATEGORIES: { value: string; label: string }[] = [
  { value: "concert", label: "Концерт" },
  { value: "theatre", label: "Театр" },
  { value: "exhibition", label: "Выставка" },
  { value: "standup", label: "Стендап" },
  { value: "party", label: "Вечеринка" },
  { value: "festival", label: "Фестиваль" },
  { value: "cinema", label: "Кино" },
  { value: "lecture", label: "Лекция" },
  { value: "tour", label: "Экскурсия" },
  { value: "quest", label: "Квест" },
  { value: "kids", label: "Детям" },
  { value: "other", label: "Другое" },
];

// Full-screen form to propose an event; posts to /v1/suggest/event → admin moderation. Kept
// self-contained (own overlay) so it drops into ProfilePanel without app-shell routing.
export function SuggestEventModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState("");
  const [venue, setVenue] = useState("");
  const [address, setAddress] = useState("");
  const [category, setCategory] = useState("");
  const [isFree, setIsFree] = useState(false);
  const [price, setPrice] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [image, setImage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  if (!open) return null;

  const canSubmit = title.trim().length >= 2 && !!date && (!!venue.trim() || !!address.trim());

  async function onPickImage(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = ""; // let the user re-pick the same file after removing
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setErr("Нужен файл-изображение");
      return;
    }
    if (f.size > 8 * 1024 * 1024) {
      setErr("Файл слишком большой — до 8 МБ");
      return;
    }
    setUploading(true);
    setErr(null);
    const res = await uploadSuggestImage(f);
    setUploading(false);
    if (res.ok) setImage(res.url);
    else setErr(res.error);
  }

  async function submit() {
    if (!canSubmit || busy) return;
    setBusy(true);
    setErr(null);
    const res = await suggestEvent({
      title: title.trim(),
      date_start: date,
      venue: venue.trim() || undefined,
      address: address.trim() || undefined,
      category: category || undefined,
      is_free: isFree,
      price_min: isFree ? 0 : price ? Number(price) : undefined,
      url: url.trim() || undefined,
      image: image || undefined,
      description: description.trim() || undefined,
    });
    setBusy(false);
    if (res.ok) {
      hapticNotify("success");
      setDone(true);
    } else {
      setErr(res.error);
      hapticNotify("error");
    }
  }

  return createPortal(
    <div className="suggest" role="dialog" aria-modal="true" aria-label="Предложить событие">
      <header className="panelview__head">
        <h2>предложить событие</h2>
        <button type="button" className="panelview__close" aria-label="Закрыть" onClick={onClose}>
          <IconClose size={18} />
        </button>
      </header>
      <div className="panelview__scroll">
        {done ? (
          <div className="suggest__done">
            <div className="suggest__done-glyph" aria-hidden="true">✓</div>
            <div className="suggest__done-title">Спасибо!</div>
            <div className="suggest__done-sub">
              Отправили на проверку. Если всё в порядке — событие появится на карте, а бот напишет тебе.
            </div>
            <button type="button" className="suggest__submit" onClick={onClose}>Готово</button>
          </div>
        ) : (
          <>
            <p className="suggest__lead">Знаешь событие, которого нет на карте? Заполни — добавим после короткой проверки.</p>

            <label className="suggest__field">
              <span className="suggest__label">Название *</span>
              <input className="suggest__input" value={title} maxLength={300}
                placeholder="Например, «Концерт в Доме культуры»"
                onChange={(e) => setTitle(e.target.value)} />
            </label>

            <label className="suggest__field">
              <span className="suggest__label">Дата и время *</span>
              <input className="suggest__input" type="datetime-local" value={date}
                onChange={(e) => setDate(e.target.value)} />
            </label>

            <label className="suggest__field">
              <span className="suggest__label">Место</span>
              <input className="suggest__input" value={venue} maxLength={300}
                placeholder="Название площадки"
                onChange={(e) => setVenue(e.target.value)} />
            </label>

            <label className="suggest__field">
              <span className="suggest__label">Адрес</span>
              <input className="suggest__input" value={address} maxLength={500}
                placeholder="Улица, дом, город"
                onChange={(e) => setAddress(e.target.value)} />
            </label>
            <div className="suggest__hint">Укажи хотя бы место или адрес — по нему поставим точку на карте.</div>

            <label className="suggest__field">
              <span className="suggest__label">Категория</span>
              <select className="suggest__input" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">— выбрать —</option>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </label>

            <div className="suggest__field">
              <span className="suggest__label">Афиша / фото</span>
              {image ? (
                <div className="suggest__photo">
                  <img src={image} alt="постер события" />
                  <button type="button" className="suggest__photo-x" onClick={() => setImage("")}>убрать</button>
                </div>
              ) : (
                <label className={"suggest__upload" + (uploading ? " suggest__upload--busy" : "")}>
                  <input type="file" accept="image/*" hidden disabled={uploading} onChange={onPickImage} />
                  <span>{uploading ? "Загружаем…" : "📷 Загрузить фото"}</span>
                </label>
              )}
            </div>

            <div className="suggest__field">
              <span className="suggest__label">Цена</span>
              <label className="suggest__free">
                <input type="checkbox" checked={isFree} onChange={(e) => setIsFree(e.target.checked)} />
                <span>Бесплатно</span>
              </label>
              {!isFree && (
                <input className="suggest__input" type="number" inputMode="numeric" min={0} value={price}
                  placeholder="Цена от, ₽" onChange={(e) => setPrice(e.target.value)} />
              )}
            </div>

            <label className="suggest__field">
              <span className="suggest__label">Ссылка</span>
              <input className="suggest__input" type="url" value={url} maxLength={1000}
                placeholder="На билеты или анонс"
                onChange={(e) => setUrl(e.target.value)} />
            </label>

            <label className="suggest__field">
              <span className="suggest__label">Описание</span>
              <textarea className="suggest__input suggest__textarea" value={description} maxLength={4000}
                placeholder="Коротко, о чём событие"
                onChange={(e) => setDescription(e.target.value)} />
            </label>

            {err && <div className="suggest__err">{err}</div>}
            <button type="button" className="suggest__submit" disabled={!canSubmit || busy} onClick={submit}>
              {busy ? "Отправляем…" : "Отправить на модерацию"}
            </button>
            <div className="suggest__fine">Заявки проверяет модератор. Спам и чужие события не пройдут.</div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
}
