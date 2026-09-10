#!/usr/bin/env python3
"""Local interactive login test; never stores passwords or tokens."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import threading

from orderflow_edge_lab.dxfeed import DEFAULT_ENDPOINT, DEFAULT_SYMBOL, probe_connection


def main():
    import tkinter as tk
    from tkinter import ttk
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="")
    parser.add_argument("--result-file", help="Optional sanitized diagnostic output; never includes credentials")
    args = parser.parse_args()
    root = tk.Tk()
    root.title("dxFeed connection test — paper research")
    root.geometry("700x520")
    root.minsize(600, 490)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    ttk.Label(frame, text="Test your existing dxFeed access", font=("Segoe UI", 16, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
    note = ("The default is dxFeed's documented REST service, not a confirmed DeepCharts endpoint. "
            "A rejection here does not rule out access through another provider endpoint.")
    ttk.Label(frame, text=note, wraplength=640).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 16))
    endpoint, symbol = tk.StringVar(value=DEFAULT_ENDPOINT), tk.StringVar(value=DEFAULT_SYMBOL)
    username, secret, method = tk.StringVar(value=args.username), tk.StringVar(), tk.StringVar(value="Username / password")
    fields = [("HTTPS endpoint", endpoint), ("Symbol", symbol), ("Username / email", username), ("Password / token", secret)]
    for row, (label, variable) in enumerate(fields, start=2):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=7)
        ttk.Entry(frame, textvariable=variable, show="*" if variable is secret else "").grid(
            row=row, column=1, sticky="ew", pady=7)
    ttk.Label(frame, text="Authentication").grid(row=6, column=0, sticky="w")
    ttk.Combobox(frame, textvariable=method, values=["Username / password", "Bearer token"], state="readonly").grid(
        row=6, column=1, sticky="ew", pady=7)
    status = tk.StringVar(value="Enter your password locally, then test. No credentials are saved.")
    results = queue.Queue()

    def connect():
        values = endpoint.get().strip(), symbol.get().strip(), username.get().strip(), secret.get(), method.get()
        if not values[3] or (values[4] == "Username / password" and not values[2]):
            status.set("Enter a username and password, or select bearer token and enter the token.")
            return
        secret.set("")
        button.configure(state="disabled")
        status.set("Testing one Quote request over HTTPS…")

        def worker():
            address, instrument, user, password, auth = values
            if auth == "Bearer token":
                outcome = probe_connection(address, password, instrument)
            else:
                outcome = probe_connection(address, None, instrument, username=user, password=password)
            results.put(outcome)
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            code, result = results.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        button.configure(state="normal")
        if code == 0:
            message = "The service responded. " + ("A valid quote was returned." if result["quote_received"] else "No usable quote was confirmed.")
        else:
            http = result.get("http_status")
            if result.get("redirect_to_public_demo"):
                message = "The server redirected to dxFeed's public demo. Your credentials were not forwarded."
            elif http and 300 <= http < 400:
                message = "The server redirected the request. Your credentials were not forwarded."
            else:
                message = f"The test failed ({'HTTP ' + str(http) if http else result.get('error_type', 'connection error')})."
        status.set(message + "\n\nThis does not verify account entitlement, real-time data, or historical TimeAndSale access. "
                   "If rejected, confirm the correct API endpoint with your provider.")
        if args.result_file:
            try:
                target = Path(args.result_file)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + ".partial")
                temporary.write_text(json.dumps({**result, "checked_at": datetime.now(timezone.utc).isoformat()}, indent=2), encoding="utf-8")
                temporary.replace(target)
            except OSError:
                status.set(status.get() + "\nThe diagnostic file could not be saved.")
        root.after(100, poll)

    button = ttk.Button(frame, text="Test connection", command=connect)
    button.grid(row=7, column=1, sticky="w", pady=14)
    ttk.Label(frame, textvariable=status, wraplength=640).grid(row=8, column=0, columnspan=2, sticky="w", pady=8)
    ttk.Label(frame, text="Read-only • No orders • No subscriptions purchased • Password cleared after submission",
              wraplength=640).grid(row=9, column=0, columnspan=2, sticky="w", pady=10)
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
