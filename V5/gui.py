"""
gui.py
------
Tkinter GUI for the C/C++ Coverage Tool.

Launcher window -> two buttons:
  - "Instrument Project"      -> opens Instrumenter window
  - "Generate HTML Report"    -> opens HTML Report window

Run:
    python3 gui.py
"""

import sys
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk

from instrument_project import instrument_file, COVERAGE_H
from html_report import generate_report


# ---------------------------------------------------------------------------
# Shared small popup: asks for outdir + logfile names (used by Instrumenter)
# ---------------------------------------------------------------------------

class OutdirLogfilePopup(simpledialog.Dialog):
    """Popup with two optional text fields: outdir name, logfile name."""

    def body(self, master):
        tk.Label(master, text="Output folder name:").grid(row=0, column=0, sticky="w", pady=4)
        self.outdir_entry = tk.Entry(master, width=30)
        self.outdir_entry.insert(0, "instrumented")
        self.outdir_entry.grid(row=0, column=1, pady=4)

        tk.Label(master, text="Log file name:").grid(row=1, column=0, sticky="w", pady=4)
        self.logfile_entry = tk.Entry(master, width=30)
        self.logfile_entry.insert(0, "coverage.log")
        self.logfile_entry.grid(row=1, column=1, pady=4)

        tk.Label(master, text="(leave as-is to use defaults)",
                 fg="#666", font=("Arial", 8)).grid(row=2, column=0, columnspan=2, pady=(4, 0))

        return self.outdir_entry

    def apply(self):
        outdir = self.outdir_entry.get().strip() or "instrumented"
        logfile = self.logfile_entry.get().strip() or "coverage.log"
        self.result = (outdir, logfile)


# ---------------------------------------------------------------------------
# Window 1 — Instrumenter
# ---------------------------------------------------------------------------

class InstrumenterWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Instrument Project")
        self.geometry("560x420")

        self.input_folder = tk.StringVar()
        self.resolved_outdir = tk.StringVar()
        self.resolved_logfile = tk.StringVar()

        pad = {"padx": 12, "pady": 6}

        # --- Input folder row ---
        frame_in = tk.Frame(self)
        frame_in.pack(fill="x", **pad)
        tk.Label(frame_in, text="Input folder:", width=14, anchor="w").pack(side="left")
        tk.Entry(frame_in, textvariable=self.input_folder, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(frame_in, text="Browse...", command=self.browse_folder).pack(side="left")

        # --- Resolved settings display (filled in after popup OK) ---
        self.resolved_frame = tk.Frame(self)
        self.resolved_frame.pack(fill="x", **pad)
        self.resolved_label = tk.Label(
            self.resolved_frame, text="", fg="#333", justify="left", anchor="w"
        )
        self.resolved_label.pack(fill="x")

        # --- Generate button ---
        tk.Button(
            self, text="Generate", command=self.on_generate, width=20, bg="#2e7d32", fg="white"
        ).pack(pady=10)

        # --- Output log box ---
        tk.Label(self, text="Output log:", anchor="w").pack(fill="x", padx=12)
        self.log_box = tk.Text(self, height=14, wrap="word", state="disabled", bg="#f7f7f7")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def browse_folder(self):
        folder = filedialog.askdirectory(title="Select project folder")
        if folder:
            self.input_folder.set(folder)

    def log(self, text: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.configure(state="disabled")
        self.log_box.see("end")

    def on_generate(self):
        folder = self.input_folder.get().strip()
        if not folder:
            messagebox.showwarning("No folder selected", "Please browse and select an input folder first.")
            return

        popup = OutdirLogfilePopup(self, title="Output Settings")
        if not getattr(popup, "result", None):
            return  # user cancelled

        outdir, logfile = popup.result
        self.resolved_outdir.set(outdir)
        self.resolved_logfile.set(logfile)

        self.resolved_label.configure(
            text=(
                f"Input folder : {folder}\n"
                f"Output folder : {outdir}\n"
                f"Log file      : {logfile}"
            )
        )

        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

        self.run_instrumentation(folder, outdir, logfile)

    def run_instrumentation(self, folder: str, outdir: str, logfile: str):
        import shutil

        folder_path = Path(folder)
        out_dir = Path(outdir)

        try:
            if out_dir.exists():
                shutil.rmtree(out_dir)
            shutil.copytree(folder_path, out_dir)

            sources = sorted(out_dir.rglob("*.c"))
            if not sources:
                self.log(f"❌  No .c files found in: {folder} (or its subfolders)")
                return

            header_content = COVERAGE_H
            if logfile != "coverage.log":
                header_content = header_content.replace('"coverage.log"', f'"{logfile}"')
            (out_dir / "coverage.h").write_text(header_content, encoding="utf-8")

            self.log(f"📂  Source folder    : {folder_path}/  ({len(sources)} .c file(s) found, including subfolders)")
            self.log(f"📁  Output directory : {out_dir}/  (full mirror)")
            self.log(f"📝  Log file         : {logfile}\n")
            self.log("Instrumenting files:")

            coverage_h_path = out_dir / "coverage.h"
            total_flags = 0
            for src_path in sources:
                flag_count = instrument_file(src_path, src_path, coverage_h_path)
                total_flags += flag_count
                self.log(f"  ✅  {src_path.relative_to(out_dir)}  ({flag_count} flags injected)")

            self.log(f"\n{'='*50}")
            self.log(f"Total flags injected: {total_flags}")
            self.log(f"{'='*50}")
            self.log(f"\nNext steps:")
            self.log(f"  1. Compile the files in {out_dir}/ with gcc")
            self.log(f"  2. Run the resulting binary (it will generate {logfile})")
            self.log(f"  3. Use the HTML Report window with your ORIGINAL folder + {logfile}")

            messagebox.showinfo("Done", f"Instrumentation complete!\n{total_flags} flags injected across {len(sources)} file(s).")

        except Exception as e:
            self.log(f"❌  Error: {e}")
            messagebox.showerror("Error", str(e))


# ---------------------------------------------------------------------------
# Window 2 — HTML Report Generator
# ---------------------------------------------------------------------------

class ReportWindow(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Generate HTML Report")
        self.geometry("560x360")

        self.source_folder = tk.StringVar()
        self.log_file = tk.StringVar()
        self.output_folder = tk.StringVar()

        pad = {"padx": 12, "pady": 6}

        # --- Source folder ---
        f1 = tk.Frame(self)
        f1.pack(fill="x", **pad)
        tk.Label(f1, text="Source folder:", width=14, anchor="w").pack(side="left")
        tk.Entry(f1, textvariable=self.source_folder, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(f1, text="Browse...", command=self.browse_source).pack(side="left")

        # --- coverage.log file ---
        f2 = tk.Frame(self)
        f2.pack(fill="x", **pad)
        tk.Label(f2, text="coverage.log:", width=14, anchor="w").pack(side="left")
        tk.Entry(f2, textvariable=self.log_file, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(f2, text="Browse...", command=self.browse_log).pack(side="left")

        # --- Output folder location ---
        f3 = tk.Frame(self)
        f3.pack(fill="x", **pad)
        tk.Label(f3, text="Output location:", width=14, anchor="w").pack(side="left")
        tk.Entry(f3, textvariable=self.output_folder, state="readonly").pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        tk.Button(f3, text="Browse...", command=self.browse_output).pack(side="left")

        # --- Generate button ---
        tk.Button(
            self, text="Generate Report", command=self.on_generate,
            width=20, bg="#1155cc", fg="white"
        ).pack(pady=14)

        # --- Status box ---
        tk.Label(self, text="Status:", anchor="w").pack(fill="x", padx=12)
        self.status_box = tk.Text(self, height=10, wrap="word", state="disabled", bg="#f7f7f7")
        self.status_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def browse_source(self):
        folder = filedialog.askdirectory(title="Select ORIGINAL source folder")
        if folder:
            self.source_folder.set(folder)

    def browse_log(self):
        path = filedialog.askopenfilename(
            title="Select coverage.log", filetypes=[("Log files", "*.log"), ("All files", "*.*")]
        )
        if path:
            self.log_file.set(path)

    def browse_output(self):
        folder = filedialog.askdirectory(title="Select where to create coverage_report/")
        if folder:
            self.output_folder.set(folder)

    def status(self, text: str):
        self.status_box.configure(state="normal")
        self.status_box.insert("end", text + "\n")
        self.status_box.configure(state="disabled")
        self.status_box.see("end")

    def on_generate(self):
        src = self.source_folder.get().strip()
        log = self.log_file.get().strip()
        outloc = self.output_folder.get().strip()

        if not src or not log or not outloc:
            messagebox.showwarning(
                "Missing info", "Please select source folder, coverage.log, and output location."
            )
            return

        self.status_box.configure(state="normal")
        self.status_box.delete("1.0", "end")
        self.status_box.configure(state="disabled")

        try:
            src_path = Path(src)
            sources = sorted(str(p) for p in src_path.rglob("*.c"))

            if not sources:
                self.status(f"❌  No .c files found in: {src}")
                return

            self.status(f"📂  Found {len(sources)} .c file(s) in {src_path}/")

            already_instrumented = [
                s for s in sources if "LOG_FLAG(" in Path(s).read_text(encoding="utf-8")
            ]
            if already_instrumented:
                self.status(f"⚠️   Warning: {len(already_instrumented)} file(s) already contain LOG_FLAG(...).")
                self.status(f"     This looks like the INSTRUMENTED folder, not the original.")

            output_dir = str(Path(outloc) / "coverage_report")
            index_path = generate_report(sources, log, output_dir, base_folder=src)

            if index_path:
                self.status(f"✅  Report written: {output_dir}/")
                self.status(f"🌐  Opening in browser...")
                webbrowser.open(Path(index_path).resolve().as_uri())
            else:
                self.status("❌  Report generation failed. Check the log file path.")

        except Exception as e:
            self.status(f"❌  Error: {e}")
            messagebox.showerror("Error", str(e))


# ---------------------------------------------------------------------------
# Launcher
# ---------------------------------------------------------------------------

class LauncherWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("C/C++ Coverage Tool")
        self.geometry("340x180")
        self.resizable(False, False)

        tk.Label(self, text="C/C++ Coverage Tool", font=("Arial", 13, "bold")).pack(pady=(20, 10))

        tk.Button(
            self, text="Instrument Project", width=24, height=2,
            command=lambda: InstrumenterWindow(self)
        ).pack(pady=6)

        tk.Button(
            self, text="Generate HTML Report", width=24, height=2,
            command=lambda: ReportWindow(self)
        ).pack(pady=6)


def main():
    app = LauncherWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
