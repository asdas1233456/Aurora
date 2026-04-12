import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";


export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function createId(prefix = "id") {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

export function shortText(value: string, max = 80) {
  const normalized = value.trim();
  if (normalized.length <= max) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, max - 3))}...`;
}

export function isUnreadablePlaceholderText(value: string) {
  const normalized = value.trim();
  if (!normalized) {
    return false;
  }
  const questionMarks = (normalized.match(/\?/g) ?? []).length;
  return questionMarks >= 6 && questionMarks / normalized.length > 0.25;
}
