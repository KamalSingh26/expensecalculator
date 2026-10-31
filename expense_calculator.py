"""Personal Expense Calculator: a Python + Tkinter + SQLite mini project.

Run this file with: python expense_calculator.py
Amounts are stored as whole paise so totals do not have floating-point errors.
"""

import csv
import re
import sqlite3
import tkinter as tk
from datetime import date
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


CATEGORIES = ("Food", "Transport", "Shopping", "Bills", "Education", "Health", "Other")
MAX_PAISE = 999_999_999
DATA_FILE = Path(__file__).resolve().with_name("expenses.db")


def parse_amount(text, allow_zero=False):
    """Convert rupees such as '125.50' to 12550 paise after validation."""
    text = text.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", text):
        raise ValueError("Enter an amount such as 250 or 250.50, without commas.")
    if len(text) > 20:
        raise ValueError("Enter an amount below Rs 1,00,00,000.")
    paise = int(Decimal(text) * 100)
    if paise < 0 or (paise == 0 and not allow_zero):
        raise ValueError("The expense amount must be greater than zero.")
    if paise > MAX_PAISE:
        raise ValueError("Enter an amount below Rs 1,00,00,000.")
    return paise


def validate_date(text):
    text = text.strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
        raise ValueError("Use YYYY-MM-DD for the date, for example 2026-10-27.")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("Enter a real calendar date.") from exc
    return text


def validate_month(text):
    text = text.strip()
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", text):
        raise ValueError("Use YYYY-MM for the month, for example 2026-10.")
    validate_date(text + "-01")
    return text


def money(paise):
    return f"Rs {Decimal(paise) / 100:,.2f}"


def amount_text(paise):
    return f"{Decimal(paise) / 100:.2f}"


class ExpenseStore:
    """Database operations, kept separate from the window for easier learning."""

    def __init__(self, path=DATA_FILE):
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY,
                    spent_on TEXT NOT NULL,
                    category TEXT NOT NULL,
                    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0),
                    note TEXT NOT NULL DEFAULT ''
                )
            """)
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    month TEXT PRIMARY KEY,
                    amount_paise INTEGER NOT NULL CHECK (amount_paise > 0)
                )
            """)
            self.connection.execute(
                "CREATE INDEX IF NOT EXISTS expense_dates ON expenses (spent_on)"
            )

    def add_expense(self, spent_on, category, amount, note=""):
        spent_on = validate_date(spent_on)
        if category not in CATEGORIES:
            raise ValueError("Choose a category from the list.")
        paise = parse_amount(amount)
        note = note.strip()
        if len(note) > 140:
            raise ValueError("Keep the note within 140 characters.")
        with self.connection:
            result = self.connection.execute(
                "INSERT INTO expenses (spent_on, category, amount_paise, note) "
                "VALUES (?, ?, ?, ?)",
                (spent_on, category, paise, note),
            )
        return result.lastrowid

    def get_expenses(self, month):
        month = validate_month(month)
        # Every saved date is valid ISO format, so text ordering matches dates.
        return self.connection.execute(
            "SELECT * FROM expenses WHERE spent_on BETWEEN ? AND ? "
            "ORDER BY spent_on DESC, id DESC",
            (month + "-01", month + "-31"),
        ).fetchall()

    def get_budget(self, month):
        month = validate_month(month)
        row = self.connection.execute(
            "SELECT amount_paise FROM budgets WHERE month = ?", (month,)
        ).fetchone()
        return row["amount_paise"] if row else None

    def set_budget(self, month, amount):
        month = validate_month(month)
        paise = parse_amount(amount, allow_zero=True)
        with self.connection:
            if paise == 0:
                self.connection.execute("DELETE FROM budgets WHERE month = ?", (month,))
            else:
                self.connection.execute(
                    "INSERT INTO budgets (month, amount_paise) VALUES (?, ?) "
                    "ON CONFLICT(month) DO UPDATE SET amount_paise = excluded.amount_paise",
                    (month, paise),
                )

    def delete_expense(self, expense_id):
        with self.connection:
            result = self.connection.execute(
                "DELETE FROM expenses WHERE id = ?", (expense_id,)
            )
        return result.rowcount > 0

    def close(self):
        self.connection.close()


def calculate_summary(rows):
    totals = {}
    for row in rows:
        category = row["category"]
        totals[category] = totals.get(category, 0) + row["amount_paise"]
    return sum(totals.values()), totals


def export_csv(path, rows):
    """Export the selected month without changing the saved database."""
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(("Date", "Category", "Amount_INR", "Note"))
        for row in rows:
            note = row["note"]
            # Keep notes as text when the CSV is opened in spreadsheet software.
            if note.lstrip().startswith(("=", "+", "-", "@")):
                note = "'" + note
            writer.writerow((row["spent_on"], row["category"],
                             amount_text(row["amount_paise"]), note))


class ExpenseCalculator:
    def __init__(self, root, database_path=DATA_FILE):
        self.root = root
        self.store = ExpenseStore(database_path)
        self.current_month = date.today().strftime("%Y-%m")
        self.month = tk.StringVar(value=self.current_month)
        self.expense_date = tk.StringVar(value=date.today().isoformat())
        self.category = tk.StringVar(value=CATEGORIES[0])
        self.amount = tk.StringVar()
        self.note = tk.StringVar()
        self.budget_input = tk.StringVar()
        self.spent_text = tk.StringVar()
        self.budget_text = tk.StringVar()
        self.remaining_text = tk.StringVar()
        self.remaining_title = tk.StringVar(value="REMAINING BUDGET")
        self.breakdown_text = tk.StringVar()
        self.table_caption = tk.StringVar()
        self.status = tk.StringVar(value="Ready. Add your first expense to get started.")
        self.rows = []
        self.build_window()
        self.refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def build_window(self):
        root = self.root
        root.title("Personal Expense Calculator")
        root.geometry("1160x760")
        root.minsize(1020, 710)
        root.configure(bg="#f2f5f9")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)
        root.option_add("*Font", ("Segoe UI", 10))

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f2f5f9")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="#f2f5f9", foreground="#172b45")
        style.configure("Card.TLabel", background="white")
        style.configure("Muted.TLabel", background="white", foreground="#607086")
        style.configure("Heading.TLabel", background="white", font=("Segoe UI", 12, "bold"))
        style.configure("TButton", padding=(12, 8))
        style.configure("Primary.TButton", background="#087f70", foreground="white")
        style.map("Primary.TButton", background=[("active", "#05685d")])
        style.configure("Treeview", rowheight=30, background="white", fieldbackground="white")
        style.configure("Treeview.Heading", padding=8, font=("Segoe UI", 10, "bold"))

        header = tk.Frame(root, bg="#172b45", padx=24, pady=20)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(header, text="Personal Expense Calculator", bg="#172b45", fg="white",
                 font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(header, text="Track spending. Plan your month.", bg="#172b45",
                 fg="#d0dde9").pack(anchor="w", pady=(4, 0))

        filters = ttk.Frame(root, padding=(24, 14))
        filters.grid(row=1, column=0, sticky="ew")
        ttk.Label(filters, text="Month (YYYY-MM)").pack(side="left", padx=(0, 8))
        month_entry = ttk.Entry(filters, textvariable=self.month, width=10)
        month_entry.pack(side="left", ipady=4)
        month_entry.bind("<Return>", lambda event: self.show_month())
        ttk.Button(filters, text="Show month", command=self.show_month).pack(side="left", padx=8)
        ttk.Label(filters, text="Monthly budget (Rs)").pack(side="left", padx=(20, 8))
        ttk.Entry(filters, textvariable=self.budget_input, width=12).pack(side="left", ipady=4)
        ttk.Button(filters, text="Save budget", command=self.save_budget).pack(side="left", padx=8)
        ttk.Label(filters, text="0 clears the budget").pack(side="left", padx=4)

        cards = ttk.Frame(root, padding=(24, 0, 24, 16))
        cards.grid(row=2, column=0, sticky="ew")
        cards.columnconfigure((0, 1, 2), weight=1, uniform="summary")
        for column, title, variable in (
            (0, "TOTAL SPENT", self.spent_text),
            (1, "MONTHLY BUDGET", self.budget_text),
            (2, self.remaining_title, self.remaining_text),
        ):
            card = ttk.Frame(cards, style="Card.TFrame", padding=(18, 14))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            title_options = {"textvariable": title} if isinstance(title, tk.StringVar) else {"text": title}
            ttk.Label(card, style="Muted.TLabel", **title_options).pack(anchor="w")
            value = ttk.Label(card, textvariable=variable, style="Card.TLabel",
                              font=("Segoe UI", 21, "bold"))
            value.pack(anchor="w", pady=(5, 0))
            if column == 2:
                self.remaining_label = value

        content = ttk.Frame(root, padding=(24, 0, 24, 0))
        content.grid(row=3, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        form = ttk.Frame(content, style="Card.TFrame", padding=20)
        form.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        form.columnconfigure(0, weight=1)
        ttk.Label(form, text="Add an expense", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 15))
        fields = (("Date (YYYY-MM-DD)", self.expense_date),
                  ("Category", self.category), ("Amount (Rs)", self.amount),
                  ("Note (optional)", self.note))
        for index, (label, variable) in enumerate(fields):
            row = 1 + index * 2
            ttk.Label(form, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w")
            if variable is self.category:
                entry = ttk.Combobox(form, textvariable=variable, values=CATEGORIES,
                                     state="readonly", width=25)
            else:
                entry = ttk.Entry(form, textvariable=variable, width=28)
            entry.grid(row=row + 1, column=0, sticky="ew", pady=(5, 12), ipady=5)
            if variable is self.amount:
                self.amount_entry = entry
                entry.bind("<Return>", lambda event: self.add_expense())
        ttk.Button(form, text="+ Add expense", style="Primary.TButton",
                   command=self.add_expense).grid(row=9, column=0, sticky="ew", pady=(3, 12))
        ttk.Label(form, text="Expenses are saved automatically.\nAll amounts are in Indian rupees.",
                  style="Muted.TLabel", wraplength=260).grid(row=10, column=0, sticky="w")

        ledger = ttk.Frame(content, style="Card.TFrame", padding=18)
        ledger.grid(row=0, column=1, sticky="nsew")
        ledger.columnconfigure(0, weight=1)
        ledger.rowconfigure(1, weight=1)
        ttk.Label(ledger, textvariable=self.table_caption, style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 12))
        table_frame = ttk.Frame(ledger, style="Card.TFrame")
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=("date", "category", "amount", "note"),
                                  show="headings", selectmode="browse", height=7)
        for name, title, width, anchor in (
            ("date", "Date", 105, "w"), ("category", "Category", 100, "w"),
            ("amount", "Amount (Rs)", 115, "e"), ("note", "Note", 210, "w"),
        ):
            self.table.heading(name, text=title)
            self.table.column(name, width=width, minwidth=75, anchor=anchor,
                              stretch=(name == "note"))
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)

        actions = ttk.Frame(ledger, style="Card.TFrame")
        actions.grid(row=2, column=0, sticky="ew", pady=12)
        ttk.Button(actions, text="Delete selected", command=self.delete_selected).pack(side="left")
        ttk.Button(actions, text="Export month to CSV", command=self.export_month).pack(side="left", padx=8)
        ttk.Label(ledger, text="CATEGORY TOTALS", style="Muted.TLabel").grid(row=3, column=0, sticky="w")
        self.breakdown_label = ttk.Label(ledger, textvariable=self.breakdown_text,
                                         style="Card.TLabel", wraplength=600, justify="left")
        self.breakdown_label.grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.breakdown_label.bind("<Configure>",
                                  lambda event: self.breakdown_label.configure(wraplength=max(100, event.width)))
        ttk.Label(root, textvariable=self.status, padding=(24, 12)).grid(row=4, column=0, sticky="ew")

    def show_month(self):
        try:
            selected_month = validate_month(self.month.get())
        except ValueError as exc:
            messagebox.showerror("Check the month", str(exc), parent=self.root)
            return
        self.current_month = selected_month
        self.refresh()
        self.status.set(f"Showing expenses for {self.current_month}.")

    def refresh(self):
        self.month.set(self.current_month)
        self.rows = self.store.get_expenses(self.current_month)
        spent, categories = calculate_summary(self.rows)
        budget = self.store.get_budget(self.current_month)
        self.spent_text.set(money(spent))
        self.budget_text.set(money(budget) if budget is not None else "Not set")
        self.budget_input.set(amount_text(budget) if budget is not None else "")
        self.remaining_title.set("REMAINING BUDGET")
        self.remaining_label.configure(foreground="#087f70")
        if budget is None:
            self.remaining_text.set("Set a budget")
        elif spent > budget:
            self.remaining_title.set("OVER BUDGET")
            self.remaining_text.set(money(spent - budget))
            self.remaining_label.configure(foreground="#b63d3d")
        else:
            self.remaining_text.set(money(budget - spent))
        for item in self.table.get_children():
            self.table.delete(item)
        for row in self.rows:
            self.table.insert("", "end", iid=str(row["id"]), values=(
                row["spent_on"], row["category"], amount_text(row["amount_paise"]), row["note"]))
        self.table_caption.set(f"{self.current_month}  |  {len(self.rows)} expense(s)")
        self.breakdown_text.set("    •    ".join(
            f"{category}: {money(total)}" for category, total in sorted(
                categories.items(), key=lambda item: (-item[1], item[0])))
            or "No expenses this month. Add one using the form.")

    def add_expense(self):
        try:
            saved_date = validate_date(self.expense_date.get())
            self.store.add_expense(saved_date, self.category.get(), self.amount.get(), self.note.get())
        except (ValueError, sqlite3.Error) as exc:
            messagebox.showerror("Could not add expense", str(exc), parent=self.root)
            return
        self.current_month = saved_date[:7]
        self.amount.set("")
        self.note.set("")
        self.refresh()
        self.amount_entry.focus_set()
        self.status.set(f"Expense saved. Showing {self.current_month}.")

    def save_budget(self):
        try:
            selected_month = validate_month(self.month.get())
            self.store.set_budget(selected_month, self.budget_input.get())
        except (ValueError, sqlite3.Error) as exc:
            messagebox.showerror("Could not save budget", str(exc), parent=self.root)
            return
        self.current_month = selected_month
        self.refresh()
        self.status.set(f"Budget updated for {self.current_month}.")

    def delete_selected(self):
        selection = self.table.selection()
        if not selection:
            messagebox.showinfo("Select an expense", "Click an expense in the table first.", parent=self.root)
            return
        if not messagebox.askyesno("Delete expense", "Delete the selected expense?", parent=self.root):
            return
        try:
            self.store.delete_expense(int(selection[0]))
        except sqlite3.Error as exc:
            messagebox.showerror("Could not delete expense", str(exc), parent=self.root)
            return
        self.refresh()
        self.status.set("Expense deleted.")

    def export_month(self):
        if not self.rows:
            messagebox.showinfo("No expenses", "There are no expenses to export for this month.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Export expenses",
            initialfile=f"expenses_{self.current_month}.csv", defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")])
        if not path:
            return
        try:
            export_csv(path, self.rows)
        except OSError as exc:
            messagebox.showerror("Could not export", str(exc), parent=self.root)
            return
        self.status.set(f"Exported {len(self.rows)} expenses to {Path(path).name}.")

    def close(self):
        self.store.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ExpenseCalculator(root)
    except sqlite3.Error as exc:
        root.withdraw()
        messagebox.showerror("Could not open the database",
            f"Keep the project in a folder you can write to, such as Documents.\n\n{exc}", parent=root)
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
