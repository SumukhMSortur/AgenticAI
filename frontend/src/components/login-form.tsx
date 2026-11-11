"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card } from "@/components/ui";

export function LoginForm() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(formData: FormData) {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/login", { method: "POST", body: formData });
      if (!response.ok) {
        const body: unknown = await response.json();
        const message =
          typeof body === "object" &&
          body !== null &&
          "detail" in body &&
          typeof body.detail === "string"
            ? body.detail
            : `Sign-in failed with status ${response.status}`;
        throw new Error(message);
      }
      router.replace("/");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign-in failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-md p-8">
      <p className="text-xs font-bold uppercase tracking-[0.16em] text-[#176b4a]">
        Supplier compliance
      </p>
      <h1 className="mt-2 text-3xl font-semibold">Sign in</h1>
      <p className="mt-2 text-sm text-[#64736a]">
        Your session is held in an HTTP-only cookie and is never exposed to browser storage.
      </p>
      <form
        className="mt-7 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit(new FormData(event.currentTarget));
        }}
      >
        <label className="block text-sm font-medium">
          Email
          <input
            className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3"
            type="email"
            name="username"
            autoComplete="username"
            required
          />
        </label>
        <label className="block text-sm font-medium">
          Password
          <input
            className="mt-1.5 min-h-11 w-full rounded-lg border border-[#cbd8cf] px-3"
            type="password"
            name="password"
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-800">
            {error}
          </p>
        )}
        <Button className="w-full" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </Card>
  );
}
