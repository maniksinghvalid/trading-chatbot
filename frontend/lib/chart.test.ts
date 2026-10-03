import { describe, expect, it } from "vitest";
import { band, daysUntil, extent, linePath, money, pctFrom, scale, signalColor, signedMoney } from "./chart";

describe("chart helpers", () => {
  it("scale maps linearly and centres a flat domain", () => {
    const s = scale(0, 10, 100, 200);
    expect(s(0)).toBe(100);
    expect(s(5)).toBe(150);
    expect(scale(3, 3, 0, 10)(3)).toBe(5);
  });

  it("extent pads, handles flat and empty input", () => {
    expect(extent([0, 10], 0.1)).toEqual([-1, 11]);
    expect(extent([5, 5])).toEqual([4, 6]);
    expect(extent([])).toEqual([0, 1]);
  });

  it("linePath breaks on gaps", () => {
    expect(linePath([[0, 1], [1, null], [2, 3], [3, 4]])).toBe("M0.0,1.0M2.0,3.0L3.0,4.0");
  });

  it("band follows the README grade table", () => {
    expect(band(29).grade).toBe("D");
    expect(band(85).grade).toBe("A+");
    expect(band(84).grade).toBe("A");
    expect(band(0).grade).toBe("F");
    expect(signalColor("caution")).toBe(band(30).color);
    expect(signalColor("STRONG BUY")).toBe(band(90).color);
    expect(signalColor(undefined)).toBe("#6d6a63");
  });

  it("formats money, signed money and % distance", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(1.55, true)).toBe("~$1.55");
    expect(signedMoney(-1.43)).toBe("−$1.43");
    expect(signedMoney(1.57)).toBe("+$1.57");
    expect(pctFrom(10, 11.23)).toBe("−11.0%");
    expect(pctFrom(13, 11.23)).toBe("+15.8%");
  });

  it("daysUntil counts whole local days", () => {
    expect(daysUntil("2026-11-05", new Date(2026, 9, 3, 15, 30))).toBe(33);
    expect(daysUntil("not-a-date")).toBeNull();
  });
});
