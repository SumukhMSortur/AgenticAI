import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

function isAllowedOrigin(origin: string | null, request: Request): boolean {
  if (!origin) return true;
  try {
    const originUrl = new URL(origin);
    const reqUrl = new URL(request.url);
    if (originUrl.origin === reqUrl.origin) return true;

    // Check host or x-forwarded-host headers
    const hostHeader = request.headers.get("x-forwarded-host") || request.headers.get("host");
    if (hostHeader) {
      const hostOnly = hostHeader.split(":")[0];
      if (originUrl.hostname === hostOnly) return true;
    }

    // Allow local development origins
    if (
      originUrl.hostname === "localhost" ||
      originUrl.hostname === "127.0.0.1" ||
      originUrl.hostname === "0.0.0.0"
    ) {
      return true;
    }
  } catch {
    return false;
  }
  return false;
}

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  const authEnabled = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

  // When auth is disabled we do not require the session cookie and do not send auth headers
  let token: string | undefined;
  if (authEnabled) {
    token = (await cookies()).get("ecochain_session")?.value;
    if (!token) return Response.json({ detail: "Authentication required" }, { status: 401 });
  }

  const method = request.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const origin = request.headers.get("origin");
    if (origin && !isAllowedOrigin(origin, request)) {
      return Response.json({ detail: "Cross-origin request rejected" }, { status: 403 });
    }
  }

  const { path } = await context.params;
  const target = new URL(
    `/${path.map((segment) => encodeURIComponent(segment)).join("/")}${new URL(request.url).search}`,
    process.env.ECOCHAIN_API_URL ?? "http://127.0.0.1:8000",
  );

  const headers = new Headers(request.headers);
  for (const name of [
    "host",
    "cookie",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
  ]) {
    headers.delete(name);
  }
  if (authEnabled && token) {
    headers.set("Authorization", `Bearer ${token}`);
  } else {
    headers.delete("Authorization");
  }

  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  const upstream = await fetch(target, {
    method,
    headers,
    body,
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers();
  for (const name of ["content-type", "etag", "cache-control", "last-modified"]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  if (responseHeaders.get("content-type")?.includes("text/event-stream")) {
    responseHeaders.set("Cache-Control", "no-cache, no-transform");
    responseHeaders.set("X-Accel-Buffering", "no");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
export const PATCH = proxy;
