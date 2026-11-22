import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, ChatClient, isRtl, textDirection } from "./chatClient";
import { translate } from "./i18n";

describe("direction helpers", () => {
  it("treats every Arabic variant as right to left", () => {
    expect(isRtl("ar")).toBe(true);
    expect(isRtl("ar-tn")).toBe(true);
    expect(isRtl("fr")).toBe(false);
    expect(isRtl(null)).toBe(false);
  });

  it("detects direction from the first strong character", () => {
    expect(textDirection("BC-10421 وين وصلت؟")).toBe("ltr");
    expect(textDirection("وين وصلت الكوموند BC-10421؟")).toBe("rtl");
    expect(textDirection("123 ...")).toBe("ltr");
  });
});

describe("translations", () => {
  it("has the same keys in every language", () => {
    expect(translate("ar", "chat_send")).toBe("إرسال");
    expect(translate("fr", "chat_human")).toBe("Parler à un conseiller");
  });
});

describe("ChatClient", () => {
  afterEach(() => vi.restoreAllMocks());

  it("sends the session token and raises structured errors", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ session_token: "tok", conversation_id: "c", expires_in: 1, customer_name: null, shop_name: "S" }), { status: 201, headers: { "content-type": "application/json" } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "rate_limited", message: "slow down" } }), { status: 429, headers: { "content-type": "application/json", "retry-after": "7" } }));
    vi.stubGlobal("fetch", fetchMock);
    const client = new ChatClient("https://api.test", "demo-shop");
    await client.start();
    const error = await client.send("hi").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(429);
    expect(error.retryAfter).toBe(7);
    const headers = fetchMock.mock.calls[1][1].headers as Headers;
    expect(headers.get("authorization")).toBe("Bearer tok");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ shop: "demo-shop" });
  });
});
