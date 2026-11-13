import { redirect } from "next/navigation";
import { LoginForm } from "@/components/login-form";

export default function LoginPage() {
  const authEnabled = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";
  if (!authEnabled) {
    redirect("/");
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[#edf3ed] p-5">
      <LoginForm />
    </main>
  );
}
