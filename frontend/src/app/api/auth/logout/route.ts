import { NextResponse } from "next/server";

export async function POST(request: Request) {
  if (request.headers.get("origin") !== new URL(request.url).origin) {
    return Response.json({ detail: "Cross-origin request rejected" }, { status: 403 });
  }
  const response = NextResponse.json({ authenticated: false });
  response.cookies.set("ecochain_session", "", {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 0,
  });
  return response;
}
