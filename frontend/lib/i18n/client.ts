"use client";

import { createInstance, type i18n as I18nInstance } from "i18next";
import { initReactI18next } from "react-i18next";
import type { SupportedLanguage } from "./config";
import en from "./locales/en.json";
import zh from "./locales/zh.json";

export function createI18nInstance(initialLanguage: SupportedLanguage): I18nInstance {
  const instance = createInstance();
  instance.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    lng: initialLanguage,
    fallbackLng: "en",
    interpolation: {
      escapeValue: false,
    },
    initImmediate: false,
  });
  return instance;
}
