// Знак Окрест-админки в стиле VITRINE: острый пин (мотив «📍 рядом») — acid-заливка + cinnabar-центр
// («ты здесь») + ink offset-тень (фирменный сдвиг, радиус 0, без скруглений). Цвета из токенов.
export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ display: "block" }}>
      {/* offset-тень */}
      <path d="M6.5 4.5 H19.5 V12.5 L13 22.5 L6.5 12.5 Z" fill="var(--ink)" />
      {/* пин */}
      <path d="M5 3 H18 V11 L11.5 21 L5 11 Z" fill="var(--acid)" />
      {/* центр «ты здесь» */}
      <rect x="8.2" y="5.6" width="5.6" height="4.8" fill="var(--cinnabar)" />
    </svg>
  );
}
