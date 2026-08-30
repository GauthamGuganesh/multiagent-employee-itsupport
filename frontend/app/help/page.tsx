import Link from "next/link";

const credentials = [
  ["EMP-034", "gavoiceai-034", "Tyler Brooks · Account Executive", "Standard employee; self-service access actions"],
  ["EMP-032", "gavoiceai-032", "Chloe Bennett · Frontend Engineer", "Software-install request that needs manager approval"],
  ["EMP-007", "gavoiceai-007", "Sofia Martins · Engineering Manager", "Manager approval authority"],
  ["EMP-022", "gavoiceai-022", "Sarah Whitfield · Platform Engineer", "Platform and production infrastructure privileges"],
  ["EMP-058", "gavoiceai-058", "Andre Bishop · Security Engineer", "Security investigation and response privileges"],
  ["EMP-046", "gavoiceai-046", "Marco Rossi · Product Manager", "Individual production-log access exception"],
  ["admin", "ga-voiceai-admin", "Command Center Administrator", "Operations dashboard and human intervention"],
];

export default function HelpPage() {
  return (
    <main className="mx-auto w-full max-w-4xl px-5 py-10 sm:px-8 sm:py-14">
      <Link href="/" className="text-sm font-medium text-primary hover:underline">← Back to sign in</Link>
      <header className="mt-7 max-w-2xl">
        <p className="text-sm font-medium text-primary">GA-VoiceAI IT Support demo</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">A quick guide to exploring the product</h1>
        <p className="mt-3 leading-7 text-muted">This fictional environment models a real IT service desk. The accounts below are safe, deterministic demo credentials — never use these patterns outside this project.</p>
      </header>

      <section className="mt-10">
        <h2 className="text-lg font-semibold">How to use it</h2>
        <ol className="mt-4 grid gap-3 text-sm leading-6 text-muted sm:grid-cols-2">
          <li className="rounded-xl border border-border-token bg-surface p-4"><span className="font-medium text-foreground">1. Sign in</span><br />Choose a sample role below and enter its employee ID and password.</li>
          <li className="rounded-xl border border-border-token bg-surface p-4"><span className="font-medium text-foreground">2. Describe a request</span><br />Try an account, device, VPN, security, or software request in plain language.</li>
          <li className="rounded-xl border border-border-token bg-surface p-4"><span className="font-medium text-foreground">3. Review the response</span><br />Follow the concise progress updates and answer any clarifying question.</li>
          <li className="rounded-xl border border-border-token bg-surface p-4"><span className="font-medium text-foreground">4. Stay in control</span><br />Confirm an action only after reading it. Use My requests to follow the resulting ticket.</li>
        </ol>
      </section>

      <section className="mt-10">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold">Sample accounts</h2>
          <p className="text-sm text-muted">Every seeded employee follows the <code className="rounded bg-surface-muted px-1.5 py-0.5">gavoiceai-###</code> password pattern.</p>
        </div>
        <div className="mt-4 overflow-hidden rounded-xl border border-border-token">
          <div className="hidden grid-cols-[0.9fr_1.1fr_1.8fr_1.6fr] gap-3 bg-surface-muted px-4 py-2.5 text-xs font-medium text-muted sm:grid"><span>Employee ID</span><span>Password</span><span>Role</span><span>What it demonstrates</span></div>
          {credentials.map(([id, password, role, capability]) => <div key={id} className="grid gap-1 border-t border-border-token px-4 py-3 text-sm sm:grid-cols-[0.9fr_1.1fr_1.8fr_1.6fr] sm:gap-3"><code className="font-medium text-foreground">{id}</code><code className="text-primary">{password}</code><span>{role}</span><span className="text-muted">{capability}</span></div>)}
        </div>
      </section>

      <section className="mt-10 rounded-xl border border-indigo-200 bg-indigo-50/60 p-5 dark:border-indigo-500/30 dark:bg-indigo-500/10">
        <h2 className="text-base font-semibold">Useful scenarios to try</h2>
        <p className="mt-2 text-sm leading-6 text-muted">“I’m locked out of my account” as EMP-034; “Install Docker Desktop on my laptop” as EMP-032; “My VPN keeps disconnecting” as EMP-014; or “I received a suspicious email” as EMP-058. The system may ask for more information, request a confirmation, create an approval, or open a ticket according to the selected employee’s privileges.</p>
      </section>
    </main>
  );
}
