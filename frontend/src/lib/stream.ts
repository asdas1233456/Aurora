export interface ParsedSseEvent {
  event: string;
  data: string;
}

export function parseSseChunk(buffer: string) {
  const frames = buffer.split("\n\n");
  const remainder = frames.pop() ?? "";
  const events = frames
    .map((frame) => parseSseFrame(frame))
    .filter((event): event is ParsedSseEvent => Boolean(event));

  return { events, remainder };
}

export function parseSseFrame(frame: string): ParsedSseEvent | null {
  const lines = frame
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean);
  if (lines.length === 0) {
    return null;
  }

  let event = "message";
  const dataParts: string[] = [];

  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim() || "message";
      continue;
    }
    if (line.startsWith("data:")) {
      dataParts.push(line.slice(5).trim());
    }
  }

  return {
    event,
    data: dataParts.join("\n"),
  };
}
