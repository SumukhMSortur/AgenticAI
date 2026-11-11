import { NextResponse } from "next/server";

const SESSION_COOKIE = "ecochain_session";

export async function POST(request: Request) {
  const form = await request.formData();
  const body = new URLSearchParams();
  for (const [key, value] of form.entries()) {
    if (typeof value === "string") body.set(key, value);
  }
  if (!body.has("scope")) body.set("scope", "");

  const upstream = await fetch(`${process.env.ECOCHAIN_API_URL ?? "http://127.0.0.1:8000"}/v1/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    cache: "no-store",
  });
  if (!upstream.ok) {
    return new Response(await upstream.text(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  }

  const result: unknown = await upstream.json();
  if (
    typeof result !== "object" ||
    result === null ||
    !("access_token" in result) ||
    typeof result.access_token !== "string" ||
    !("expires_in" in result) ||
    typeof result.expires_in !== "number" ||
    result.expires_in <= 0
  ) {
    return Response.json({ detail: "Authentication service returned an invalid token response" }, {
      status: 502,
    });
  }

  const response = NextResponse.json({ authenticated: true });
  response.cookies.set(SESSION_COOKIE, result.access_token, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: result.expires_in,
  });
  return response;
}
