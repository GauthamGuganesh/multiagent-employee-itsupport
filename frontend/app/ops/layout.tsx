import { OpsShell } from "@/components/ops-shell";

export default function OpsLayout({ children }: LayoutProps<"/ops">) {
  return <OpsShell>{children}</OpsShell>;
}
