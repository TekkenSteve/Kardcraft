export const LANGUAGE_COOKIE_KEY = "kc_language";
export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export function isSupportedLanguage(value: string | undefined): value is SupportedLanguage {
  return value === "en" || value === "zh";
}

export function resolveLanguage(value: string | undefined): SupportedLanguage {
  return isSupportedLanguage(value) ? value : "en";
}
