/** F51 Contract H: the invite page no longer reads the envelope itself — `lib/http.ts` turns any refusal
 * into the server's sentence, the string envelope `{error: "…"}` included (the page used to read only
 * `error.message` and printed its 「加入失敗（狀態碼 N）」 fallback for it). */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("@/lib/auth", () => ({ setOrgId: vi.fn() }));

import { setOrgId } from "@/lib/auth";
import { apiFetch } from "@/lib/http";
import { AcceptInvitePage } from "./AcceptInvitePage";

const mockApiFetch = vi.mocked(apiFetch);

afterEach(() => {
  vi.clearAllMocks();
});

function page() {
  return render(
    <MemoryRouter initialEntries={["/accept-invite?token=abc"]}>
      <AcceptInvitePage />
    </MemoryRouter>,
  );
}

const reply = (body: unknown, status: number) => new Response(JSON.stringify(body), { status });

describe("AcceptInvitePage", () => {
  it("a {error: string} refusal shows its sentence", async () => {
    mockApiFetch.mockResolvedValue(reply({ error: "這個邀請已經過期，請跟邀請你的人要一份新的連結。" }, 410));
    page();
    expect(await screen.findByText("這個邀請已經過期，請跟邀請你的人要一份新的連結。")).toBeTruthy();
    expect(setOrgId).not.toHaveBeenCalled();
  });

  it("an object-envelope refusal shows its message", async () => {
    mockApiFetch.mockResolvedValue(reply({ error: { code: "invite_used", message: "這個邀請已經用過了。" } }, 409));
    page();
    expect(await screen.findByText("這個邀請已經用過了。")).toBeTruthy();
  });

  it("an accepted invite lands in the joined org", async () => {
    mockApiFetch.mockResolvedValue(reply({ org: { id: "org_team", name: "團隊", kind: "company", role: "member" } }, 200));
    page();
    expect(await screen.findByText("已經加入「團隊」。")).toBeTruthy();
    expect(setOrgId).toHaveBeenCalledWith("org_team");
  });
});
