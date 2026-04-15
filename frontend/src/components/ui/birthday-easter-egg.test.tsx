import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { BirthdayEasterEgg } from "./birthday-easter-egg";


describe("BirthdayEasterEgg", () => {
  it("renders 星空's birthday letter when opened", () => {
    render(<BirthdayEasterEgg open onOpenChange={vi.fn()} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "星空的生日信" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "致星空老板 · 生日快乐 🎂" })).toBeInTheDocument();
    expect(screen.getByText("愿你终于开始，对自己温柔以待。")).toBeInTheDocument();
    expect(screen.getByText(/没事，有我在/)).toBeInTheDocument();
  });
});
