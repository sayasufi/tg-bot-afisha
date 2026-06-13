// Only allow http(s) URLs — blocks javascript:/data:/other schemes from
// reaching an href, an <img src>, or a CSS url().
export function safeHttpUrl(u: string | null | undefined): string | null {
  if (!u) return null;
  try {
    const parsed = new URL(u);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : null;
  } catch {
    return null;
  }
}
