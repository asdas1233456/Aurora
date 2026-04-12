export function formatNumber(value: number | string | null | undefined) {
  const normalized = Number(value ?? 0);
  if (!Number.isFinite(normalized)) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN").format(normalized);
}

export function formatBytes(value: number | null | undefined) {
  const normalized = Number(value ?? 0);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = normalized;
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) {
    amount /= 1024;
    index += 1;
  }

  const digits = amount >= 10 || index === 0 ? 0 : 1;
  return `${amount.toFixed(digits)} ${units[index]}`;
}

export function formatDuration(value: number | null | undefined) {
  const normalized = Number(value ?? 0);
  if (!Number.isFinite(normalized) || normalized <= 0) {
    return "--";
  }
  if (normalized < 1000) {
    return `${Math.round(normalized)} ms`;
  }
  return `${(normalized / 1000).toFixed(2)} s`;
}

export function formatConfidence(value: number | null | undefined) {
  const normalized = Number(value ?? 0);
  if (!Number.isFinite(normalized)) {
    return "0%";
  }
  return `${Math.round(normalized * 100)}%`;
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatRelativeTime(value: string | null | undefined) {
  if (!value) {
    return "--";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const diff = Date.now() - date.getTime();
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  if (diff < minute) {
    return "刚刚";
  }
  if (diff < hour) {
    return `${Math.floor(diff / minute)} 分钟前`;
  }
  if (diff < day) {
    return `${Math.floor(diff / hour)} 小时前`;
  }
  return `${Math.floor(diff / day)} 天前`;
}
