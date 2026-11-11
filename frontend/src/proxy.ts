import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const isLogin = request.nextUrl.pathname === "/login";
  const isAuthApi = request.nextUrl.pathname.startsWith("/api/auth/");
  const hasSession = Boolean(request.cookies.get("ecochain_session")?.value);

  if (isAuthApi) return NextResponse.next();
  if (!hasSession && !isLogin) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(login);
  }
  if (hasSession && isLogin) return NextResponse.redirect(new URL("/", request.url));
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
