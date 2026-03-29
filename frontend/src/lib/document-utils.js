export function parseTagsInput(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item, index, array) => array.indexOf(item) === index);
}

export function stringifyTags(tags) {
  return Array.isArray(tags) ? tags.join(", ") : "";
}

export function inferCategory(fileName) {
  const stem = String(fileName || "").replace(/\.[^.]+$/, "");
  if (!stem) {
    return "未分类";
  }

  const normalizedStem = /^\d+_/.test(stem) ? stem.replace(/^\d+_/, "") : stem;
  const normalized = normalizedStem.replace(/[-_]+/g, " ").trim();
  if (!normalized) {
    return "未分类";
  }

  return normalized
    .split(/\s+/)
    .slice(0, 3)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatPercent(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount)) {
    return "0%";
  }
  return `${Math.round(amount * 100)}%`;
}

export function formatConfidence(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    return "--";
  }
  return amount.toFixed(2);
}
