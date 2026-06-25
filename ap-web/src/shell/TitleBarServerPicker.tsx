import { useCallback, useEffect, useState } from "react";
import { CheckIcon, ChevronDownIcon, PlusIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  getHostStatus,
  getLocalServerStatus,
  getServerPicker,
  onHostStatusChanged,
  openServerSetup,
  setHostEnabled,
  switchServer,
  type HostStatus,
  type LocalServerStatus,
  type ServerPickerInfo,
} from "@/lib/nativeBridge";
import { cn } from "@/lib/utils";

/** Short display label for a server URL — its host, e.g. "localhost:8000". */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/** Origin of a server URL, for matching recents against the current origin. */
function originOf(url: string): string | null {
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

/**
 * Tailwind color for the host-connection dot: green when fully connected,
 * amber while a host process is up but not yet tunneled (connecting/degraded),
 * muted when off or the CLI is missing.
 */
function hostDotTone(status: HostStatus | null): string {
  if (!status || !status.cliInstalled) return "bg-muted-foreground/40";
  if (status.connected) return "bg-success";
  if (status.process === "online" || status.ownedByDesktop) return "bg-warning";
  return "bg-muted-foreground/40";
}

/** One-line summary of host status for the dropdown sub-label. */
function hostSummary(status: HostStatus | null, enabled: boolean): string {
  if (status && !status.cliInstalled) return "Omnigent CLI not found";
  if (status?.error) return status.error;
  if (status?.connected) {
    return status.sessions > 0
      ? `Connected · ${status.sessions} session${status.sessions === 1 ? "" : "s"}`
      : "Connected";
  }
  if (enabled) return "Connecting…";
  return "This machine is not hosting";
}

/**
 * Centered title-bar server picker for the macOS Electron shell.
 *
 * The shell hides the native title bar (titleBarStyle "hiddenInset"), so the
 * strip at the top of the window — normally the OS title — is blank canvas
 * owned by the web layer. This fills its center with "Omnigent — <host>" and
 * a chevron; clicking opens a menu of recently-connected servers (switching
 * re-points the whole window via the shell) plus "Connect to new server…",
 * which returns the window to the shell's setup page.
 *
 * The menu also surfaces desktop server management: a live host-connection dot
 * on the trigger plus a "Host on this machine" toggle and local-server status
 * inside. Hosting means this machine runs the agent work the server dispatches,
 * so it stays an explicit opt-in (the shell connects only when toggled on).
 *
 * When a thread is open, its title replaces the "Omnigent" brand label
 * (becoming "<title> — <host>") so the window title tracks what the user
 * is looking at, like a document window.
 *
 * Renders nothing until the shell confirms this page is a connected server
 * (getServerPicker resolves non-null) — so it's absent in plain browsers,
 * under shells too old for the picker IPC, and on foreign pages.
 */
export function TitleBarServerPicker({
  threadTitle,
}: {
  /** Title of the currently open thread, or null/undefined when no thread
      is selected or it has no title yet (falls back to "Omnigent"). */
  threadTitle?: string | null;
}) {
  const [info, setInfo] = useState<ServerPickerInfo | null>(null);
  const [host, setHost] = useState<HostStatus | null>(null);
  const [server, setServer] = useState<LocalServerStatus | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void getServerPicker().then((result) => {
      if (!cancelled) setInfo(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  // Refresh host + local-server status from the shell (null off-shell / remote).
  const refreshHost = useCallback(() => {
    void getHostStatus().then(setHost);
    void getLocalServerStatus().then(setServer);
  }, []);

  // Initial read plus the shell's pushed updates (timer + post-toggle), so the
  // dot and toggle stay live without polling here.
  useEffect(() => {
    refreshHost();
    return onHostStatusChanged((status) => {
      setHost(status);
      void getLocalServerStatus().then(setServer);
    });
  }, [refreshHost]);

  if (!info) return null;

  // The current server leads the list even when the recents file was edited
  // out from under us; recents matching the current origin collapse into it.
  const others = info.recentServers.filter((url) => originOf(url) !== info.currentOrigin);

  // "On" = connected, or owned-by-this-app (we started it and it may still be
  // tunneling). The CLI being absent disables the toggle outright.
  const hostEnabled = Boolean(host && (host.connected || host.ownedByDesktop));
  const cliMissing = Boolean(host && !host.cliInstalled);

  async function toggleHost(next: boolean) {
    setBusy(true);
    try {
      await setHostEnabled(next);
    } finally {
      // The shell broadcasts after a toggle, but refetch so the UI settles even
      // if that push is missed.
      refreshHost();
      setBusy(false);
    }
  }

  return (
    /* Sits over the drag strip; the button itself is no-drag via the blanket
       [data-electron-mac] rule in index.css, so it stays clickable. */
    <div className="pointer-events-none absolute inset-x-0 top-0 z-40 flex h-9 justify-center">
      <DropdownMenu>
        <DropdownMenuTrigger
          className={cn(
            "pointer-events-auto flex max-w-72 items-center gap-1.5 rounded-md px-2 text-xs",
            "my-1 text-muted-foreground hover:bg-foreground/5 hover:text-foreground",
            "data-[state=open]:bg-foreground/5 data-[state=open]:text-foreground",
          )}
          title="Switch server"
        >
          {/* Host-connection dot — only once the shell reports host status. */}
          {host && (
            <span
              aria-hidden="true"
              className={cn("size-2 shrink-0 rounded-full", hostDotTone(host))}
            />
          )}
          <span className="truncate font-medium">
            {threadTitle || "Omnigent"} — {hostOf(info.currentOrigin)}
          </span>
          <ChevronDownIcon className="size-3 shrink-0" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="center" className="min-w-64">
          {/* Host-on-this-machine control (only under the desktop shell). A raw
              block, not a menu item, so toggling the switch doesn't close the
              menu. */}
          {host && (
            <>
              <div className="px-2 py-1.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={cn("size-2 shrink-0 rounded-full", hostDotTone(host))}
                    />
                    <span className="truncate text-xs font-medium">Host on this machine</span>
                  </div>
                  <Switch
                    size="sm"
                    checked={hostEnabled}
                    disabled={busy || cliMissing}
                    onCheckedChange={(v) => void toggleHost(v)}
                    aria-label="Host on this machine"
                  />
                </div>
                <p
                  className="mt-1 truncate pl-4 text-xs text-muted-foreground"
                  title={hostSummary(host, hostEnabled)}
                >
                  {hostSummary(host, hostEnabled)}
                </p>
                {server && (
                  <p className="truncate pl-4 text-xs text-muted-foreground">
                    Local server · {server.running ? "running" : "stopped"}
                    {server.running && server.liveSessions > 0
                      ? ` · ${server.liveSessions} active`
                      : ""}
                  </p>
                )}
              </div>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            Server
          </DropdownMenuLabel>
          <DropdownMenuItem disabled className="gap-2 opacity-100">
            <CheckIcon className="size-4 shrink-0" />
            <span className="truncate">{hostOf(info.currentOrigin)}</span>
          </DropdownMenuItem>
          {others.map((url) => (
            <DropdownMenuItem key={url} className="gap-2" onSelect={() => void switchServer(url)}>
              {/* Spacer aligns hosts under the current-server check. */}
              <span className="size-4 shrink-0" aria-hidden="true" />
              <span className="truncate">{hostOf(url)}</span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem className="gap-2" onSelect={() => openServerSetup()}>
            <PlusIcon className="size-4 shrink-0" />
            Connect to new server…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
