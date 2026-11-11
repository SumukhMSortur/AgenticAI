import { cookies } from "next/headers";

export const dynamic = "force-dynamic";

type RouteContext = { params: Promise<{ path: string[] }> };

async function proxy(request: Request, context: RouteContext): Promise<Response> {
  const token = (await cookies()).get("ecochain_session")?.value;
  if (!token) return Response.json({ detail: "Authentication required" }, { status: 401 });

  const method = request.method.toUpperCase();
  if (method !== "GET" && method !== "HEAD" && method !== "OPTIONS") {
    const origin = request.headers.get("origin");
    if (origin !== new URL(request.url).origin) {
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
  headers.set("Authorization", `Bearer ${token}`);

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