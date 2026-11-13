"use client";

import {
  Activity,
  ClipboardCheck,
  FileClock,
  Factory,
  FileUp,
  LayoutDashboard,
  LogOut,
  Plug,
  ScrollText,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui";

const links = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/jobs", label: "New check", icon: FileUp },
  { href: "/reviews", label: "Review queue", icon: ClipboardCheck },
  { href: "/factories", label: "Factory risk", icon: Factory },
  { href: "/audit", label: "Audit trail", icon: ScrollText },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/admin/regulations", label: "Regulation updates", icon: FileClock },
];

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [logoutError, setLogoutError] = useState<string | null>(null);

  async function logout() {
    setLogoutError(null);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Unable to end the current session");
      router.replace("/login");
    } catch (reason) {
      setLogoutError(reason instanceof Error ? reason.message : "Unable to end the current session");
    }
  }

  return (
    <div className="min-h-screen md:flex">
      <aside className="flex w-full flex-col border-b border-[#dce5dd] bg-white p-4 md:min-h-screen md:w-64 md:border-b-0 md:border-r md:p-5">
        <Link href="/" className="mb-6 flex items-center gap-3 px-2">
          <span className="grid size-10 place-items-center rounded-xl bg-[#176b4a] text-white">
            <Activity size={21} aria-hidden="true" />
          </span>
          <span>
            <span className="block font-bold">EcoChain</span>
            <span className="text-xs text-[#64736a]">Compliance workspace</span>
          </span>
        </Link>

        {/* Demo mode badge */}
        {!AUTH_ENABLED && (
          <div
            className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
            role="status"
            aria-label="Demo mode active"
          >
            <span className="font-semibold">Demo mode</span>
            <span className="ml-1 text-amber-700">— auth disabled, using sample data</span>
          </div>
        )}

        <nav aria-label="Main navigation" className="grid grid-cols-2 gap-1 md:block md:flex-1">
          {links.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "mb-1 flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium",
                  active
                    ? "bg-[#eaf4ed] text-[#10553a]"
                    : "text-[#56665c] hover:bg-[#f4f7f4]",
                )}
              >
                <Icon size={17} aria-hidden="true" />
                {label}
              </Link>
            );
          })}
        </nav>

        {/* Only show sign-out when auth is enabled */}
        {AUTH_ENABLED && (
          <Button
            variant="secondary"
            className="mt-4 justify-start"
            onClick={() => void logout()}
            aria-label="Sign out"
          >
            <LogOut size={16} className="mr-2" aria-hidden="true" />
            Sign out
          </Button>
        )}
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8">
        <div className="mx-auto w-full max-w-7xl">
          {logoutError && <p role="alert" className="mb-5 rounded-xl bg-red-50 p-4 text-sm text-red-800">{logoutError}</p>}
          {children}
        </div>
      </main>
    </div>
  );
}
