import type { ButtonHTMLAttributes, HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLElement>) {
  return (
    <section
      className={cn("rounded-2xl border border-[#dce5dd] bg-white p-5 shadow-sm", className)}
      {...props}
    />
  );
}

export function Button({
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const styles = {
    primary: "bg-[#176b4a] text-white hover:bg-[#10553a]",
    secondary: "border border-[#cbd8cf] bg-white text-[#24352b] hover:bg-[#f1f6f2]",
    danger: "bg-[#a02e2e] text-white hover:bg-[#822424]",
  };
  return (
    <button
      className={cn(
        "inline-flex min-h-10 items-center justify-center rounded-lg px-4 py-2 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        styles[variant],
        className,
      )}
      {...props}
    />
  );
}

export function StatusBadge({ children }: { children: string }) {
  const color =
    children === "critical" || children === "fail" || children === "non_compliant"
      ? "bg-red-100 text-red-800"
      : children === "pass" || children === "compliant" || children === "healthy"
        ? "bg-emerald-100 text-emerald-800"
        : "bg-amber-100 text-amber-900";
  return (
    <span className={cn("inline-flex rounded-full px-2.5 py-1 text-xs font-semibold", color)}>
      {children.replaceAll("_", " ")}
    </span>
  );
}

export function PageTitle({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-[#176b4a]">
          EcoChain Copilot
        </p>
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm text-[#64736a]">{description}</p>
      </div>
      {action}
    </div>
  );
}
