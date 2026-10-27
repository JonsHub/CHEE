import json
import re
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

BASE_URL = "https://hapi.fhir.org/baseR4"
TIMEOUT = 25
KBV_PROFILE = "https://fhir.kbv.de/StructureDefinition/KBV_PR_Base_Patient"

# --- Extension URLs used by the German base profile --------------------------
EXT_NAMENSZUSATZ = "http://fhir.de/StructureDefinition/humanname-namenszusatz"
EXT_NACHNAME = "http://hl7.org/fhir/StructureDefinition/humanname-own-name"
EXT_VORSATZWORT = "http://hl7.org/fhir/StructureDefinition/humanname-own-prefix"
EXT_GENDER_AMTLICH = "http://fhir.de/StructureDefinition/gender-amtlich-de"
EXT_DATA_ABSENT = "http://hl7.org/fhir/StructureDefinition/data-absent-reason"

GENDER = {"male": "male", "female": "female",
          "other": "other / indeterminate", "unknown": "unknown"}
GENDER_AMTLICH = {"D": "diverse", "X": "indeterminate"}
MARITAL = {"A": "annulled", "D": "divorced", "I": "interim", "L": "legally separated",
           "M": "married", "P": "polygamous", "S": "single", "T": "civil partnership",
           "U": "unmarried", "W": "widowed", "UNK": "unknown"}
ID_SYSTEMS = {"http://fhir.de/sid/gkv/kvid-10": "GKV insurance number (KVID-10)",
              "http://fhir.de/sid/pkv/kvid-10": "PKV insurance number (KVID-10)",
              "http://fhir.de/sid/gkv/kvk-versichertennummer": "KVK insurance number"}
ID_TYPES = {"GKV": "GKV insurance number", "PKV": "PKV insurance number",
            "MR": "medical record number", "PI": "patient identifier", "KVZ10": "KVID-10"}
TELECOM = {"phone": "Phone", "fax": "Fax", "email": "Email", "url": "Website",
           "sms": "SMS", "pager": "Pager", "other": "Other"}
USE = {"home": "home", "work": "work", "temp": "temporary", "old": "old",
       "mobile": "mobile", "official": "official", "usual": "usual", "nickname": "nickname",
       "anonymous": "anonymous", "maiden": "maiden name", "billing": "billing"}
ADDR_TYPE = {"postal": "postal address", "physical": "street address",
             "both": "postal and street address"}

# --- Farben / Fonts ----------------------------------------------------------
BG, CARD, ACCENT, TITLE, MUTED = "#f4f6f8", "#ffffff", "#0b78c4", "#e3c164", "#6b7280"
F_BASE = ("Segoe UI", 10)
F_BOLD = ("Segoe UI", 10, "bold")
F_HEAD = ("Segoe UI", 11, "bold")
F_TITLE = ("Segoe UI", 16, "bold")


# =============================================================================
# FHIR-Zugriff
# =============================================================================
class FhirError(Exception):
    pass

def fhir_get(path: str) -> dict:
    """Fuehrt einen FHIR-GET aus und gibt die JSON-Ressource zurueck."""
    req = urllib.request.Request(
        f"{BASE_URL}/{path}",
        headers={"Accept": "application/fhir+json", "User-Agent": "CHEE/0.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if not isinstance(payload, dict) or not payload.get("resourceType"):
                raise FhirError("The server returned an invalid FHIR resource.")
            return payload
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            oo = json.loads(e.read().decode("utf-8"))
            detail = oo["issue"][0].get("diagnostics") or oo["issue"][0].get("details", {}).get("text", "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            pass
        raise FhirError(f"HTTP {e.code} {e.reason}" + (f" – {detail}" if detail else "")) from e
    except urllib.error.URLError as e:
        raise FhirError(f"Server is unreachable: {e.reason}") from e
    except TimeoutError as e:
        raise FhirError("The request timed out.") from e


def lookup(query: str):
    """Fetch a patient by ID or search for patients by name."""
    query = query.strip()
    if not query:
        bundle = fhir_get("Patient?_count=20&_sort=-_lastUpdated")
        return _from_bundle(bundle), "Latest patients"
    if re.fullmatch(r"[A-Za-z0-9\-.]{1,64}", query):
        try:
            res = fhir_get(f"Patient/{urllib.parse.quote(query)}")
            if res.get("resourceType") == "Patient":
                return [res], f"Patient/{query} loaded"
        except FhirError as e:
            if not any(code in str(e) for code in ("404", "410")):
                raise
    bundle = fhir_get(f"Patient?name={urllib.parse.quote(query)}&_count=20")
    return _from_bundle(bundle), f"Name search: {query!r}"


def _from_bundle(bundle: dict):
    if bundle.get("resourceType") != "Bundle":
        raise FhirError("The search response was not a FHIR Bundle.")
    return [e["resource"] for e in bundle.get("entry", [])
            if e.get("resource", {}).get("resourceType") == "Patient"]


# =============================================================================
# Patient data mapping (KBV_PR_Base_Patient)
# =============================================================================
def ext_value(el: dict, url: str):
    for e in (el or {}).get("extension", []):
        if e.get("url") == url:
            for k, v in e.items():
                if k.startswith("value"):
                    return v
    return None


def mapped_text(mapping: dict[str, str], value):
    """Liefert die Bezeichnung fuer einen optionalen FHIR-Code."""
    return mapping.get(value, value) if isinstance(value, str) else value


def fmt_date(s):
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?(?:T.*)?", s)
    if not m:
        return s
    y, mo, d = m.groups()
    return ".".join(p for p in (d, mo, y) if p)


def code_text(cc: dict | None):
    if not cc:
        return None
    if cc.get("text"):
        return cc["text"]
    for c in cc.get("coding", []):
        return c.get("display") or c.get("code")
    return None


def name_rows(n: dict):
    fam_ext = n.get("_family", {})
    nachname = ext_value(fam_ext, EXT_NACHNAME) or n.get("family")
    rows = [
        ("Family name", nachname),
        ("Given name", " ".join(n.get("given", [])) or None),
        ("Prefix", " ".join(n.get("prefix", [])) or None),
        ("Name suffix", ext_value(fam_ext, EXT_NAMENSZUSATZ)),
        ("Name prefix word", ext_value(fam_ext, EXT_VORSATZWORT)),
        ("Use", mapped_text(USE, n.get("use"))),
    ]
    if n.get("text"):
        rows.append(("Full name", n["text"]))
    return rows


def address_rows(a: dict):
    street = " ".join(a.get("line", [])) or None
    plz_ort = " ".join(x for x in (a.get("postalCode"), a.get("city")) if x) or None
    return [
        ("Type", mapped_text(ADDR_TYPE, a.get("type"))),
        ("Street / PO box", street),
        ("Postal code / city", plz_ort),
        ("State", a.get("state")),
        ("Country", a.get("country")),
        ("Use", mapped_text(USE, a.get("use"))),
    ]


def identifier_label(i: dict):
    sys_ = i.get("system", "")
    if sys_ in ID_SYSTEMS:
        return ID_SYSTEMS[sys_]
    for c in (i.get("type") or {}).get("coding", []):
        if c.get("code") in ID_TYPES:
            return ID_TYPES[c["code"]]
    return code_text(i.get("type")) or sys_.rsplit("/", 1)[-1] or "Identifier"


def display_name(p: dict):
    names = p.get("name", [])
    if not names:
        return "(no name)"
    rows = dict(name_rows(names[0]))
    parts = [rows.get("Prefix"), rows.get("Given name"), rows.get("Name prefix word"), rows.get("Family name")]
    return " ".join(x for x in parts if x) or "(no name)"


def build_sections(p: dict):
    """Return sections of labelled values for the patient profile view."""
    sections = []

    # Demographic data ---------------------------------------------------------
    gender = mapped_text(GENDER, p.get("gender"))
    amtlich = ext_value(p.get("_gender", {}), EXT_GENDER_AMTLICH)
    if isinstance(amtlich, dict):
        amtlich = amtlich.get("code")
    if amtlich:
        gender = f"{gender} ({mapped_text(GENDER_AMTLICH, amtlich)})"

    birth = fmt_date(p.get("birthDate"))
    if not birth and p.get("_birthDate"):
        birth = "(not provided - data-absent-reason)"

    if "deceasedBoolean" in p:
        deceased = "Yes" if p["deceasedBoolean"] else "No"
    elif "deceasedDateTime" in p:
        deceased = f"Yes, on {fmt_date(p['deceasedDateTime'])}"
    else:
        deceased = None

    marital = p.get("maritalStatus")
    marital_txt = None
    if marital:
        code = next((c.get("code") for c in marital.get("coding", []) if c.get("code")), None)
        marital_txt = mapped_text(MARITAL, code) or code_text(marital)

    sections.append(("Demographic data", [
        ("Gender", gender),
        ("Birth date", birth),
        ("Deceased", deceased),
        ("Marital status", marital_txt),
    ]))

    # Names --------------------------------------------------------------------
    for i, n in enumerate(p.get("name", []), 1):
        sections.append((f"Name {i}" if len(p["name"]) > 1 else "Name", name_rows(n)))

    # Identifiers ---------------------------------------------------------------
    ids = [(identifier_label(i), i.get("value")) for i in p.get("identifier", [])]
    if ids:
        sections.append(("Identifiers", ids))

    # Addresses -----------------------------------------------------------------
    for i, a in enumerate(p.get("address", []), 1):
        sections.append((f"Address {i}" if len(p["address"]) > 1 else "Address", address_rows(a)))

    # Contact details -----------------------------------------------------------
    tel = []
    for t in p.get("telecom", []):
        use = mapped_text(USE, t.get("use"))
        label = mapped_text(TELECOM, t.get("system")) or "Contact"
        tel.append((f"{label}" + (f" ({use})" if use else ""), t.get("value")))
    if tel:
        sections.append(("Contact details", tel))

    # Contact persons -----------------------------------------------------------
    for i, c in enumerate(p.get("contact", []), 1):
        rows = []
        if c.get("name"):
            rows += [(k, v) for k, v in name_rows(c["name"]) if k != "Use"]
        rows.append(("Relationship", ", ".join(filter(None, (code_text(r) for r in c.get("relationship", []))))))
        for t in c.get("telecom", []):
            rows.append((mapped_text(TELECOM, t.get("system")) or "Contact", t.get("value")))
        sections.append((f"Contact person {i}", rows))

    # Communication -------------------------------------------------------------
    comm = []
    for c in p.get("communication", []):
        lang = code_text(c.get("language"))
        if lang:
            comm.append(("Language" + (" (preferred)" if c.get("preferred") else ""), lang))
    if comm:
        sections.append(("Communication", comm))

    # Metadata ------------------------------------------------------------------
    meta = p.get("meta", {})
    profiles = meta.get("profile", [])
    kbv = any(pr.startswith(KBV_PROFILE) for pr in profiles)
    sections.append(("Metadata", [
        ("Resource ID", p.get("id")),
        ("Version", meta.get("versionId")),
        ("Last updated", meta.get("lastUpdated")),
        ("Declared profiles", "\n".join(profiles) or "-"),
        ("KBV_PR_Base_Patient", "declared ✓" if kbv else "not declared"),
    ]))
    return sections


def conformity_hints(p: dict):
    """Check the required fields of the profile (name 1..*, birthDate 1..1)."""
    hints = []
    if not p.get("name"):
        hints.append("name ✘ missing")
    if not p.get("birthDate") and not p.get("_birthDate"):
        hints.append("birthDate ✘ missing")
    return hints


# =============================================================================
# GUI
# =============================================================================
class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BG)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", self._bind_wheel)
            w.bind("<Leave>", self._unbind_wheel)

    def _bind_wheel(self, _):
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120 or (1 if e.delta > 0 else -1)), "units"))
        self.canvas.bind_all("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))
        self.canvas.bind_all("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

    def _unbind_wheel(self, _):
        for ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(ev)

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)


class Chase(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CHEE - Comprehensive FHIR Engine - Patient Viewer")
        self.geometry("1240x780")
        self.minsize(1000, 620)
        self.configure(bg=BG)
        self.patients = {}
        self._busy = False
        self._style()
        self._build()
        self._show_welcome()

    # -- Layout ----------------------------------------------------------------
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", font=F_BASE, background=BG)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG)
        s.configure("Accent.TButton", font=F_BOLD, background=ACCENT, foreground="white", padding=(16, 6))
        s.map("Accent.TButton", background=[("active", "#095f9c"), ("disabled", "#9ca3af")])
        s.configure("Treeview", rowheight=30, font=F_BASE)
        s.configure("Treeview.Heading", font=F_BOLD)
        s.configure("TNotebook", background=BG)
        s.configure("TNotebook.Tab", padding=(14, 6), font=F_BASE)

    def _build(self):
        head = ttk.Frame(self, padding=(16, 12, 16, 4))
        head.pack(fill="x")
        ttk.Label(head, text="CHEE", font=F_TITLE, foreground=TITLE).pack(side="left")
        ttk.Label(head, text="  FHIR R4 · KBV_PR_Base_Patient", foreground=MUTED).pack(side="left", pady=(6, 0))
        ttk.Label(head, text=BASE_URL, foreground=MUTED).pack(side="right", pady=(6, 0))

        bar = ttk.Frame(self, padding=(16, 6, 16, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Patient ID or name:").pack(side="left")
        self.entry = ttk.Entry(bar, width=42, font=F_BASE)
        self.entry.pack(side="left", padx=10, ipady=3)
        self.entry.bind("<Return>", lambda e: self.start_lookup())
        self.entry.focus_set()
        self.btn = ttk.Button(bar, text="Fetch", style="Accent.TButton", command=self.start_lookup)
        self.btn.pack(side="left")
        ttk.Label(bar, text="empty = latest patients", foreground=MUTED).pack(side="left", padx=10)

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=16, pady=(0, 6))

        left = ttk.Frame(paned, width=390)
        left.pack_propagate(False)
        self.tree = ttk.Treeview(left, columns=("id",), show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Name")
        self.tree.heading("id", text="ID")
        self.tree.column("#0", width=245, minwidth=210, stretch=True)
        self.tree.column("id", width=130, minwidth=110, anchor="w", stretch=False)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        paned.add(left, weight=1)

        right = ttk.Notebook(paned)
        self.profile = ScrollFrame(right)
        self.json_box = ScrolledText(right, font=("Consolas", 10), wrap="none", relief="flat")
        self.json_box.configure(state="disabled")
        right.add(self.profile, text="  Profile  ")
        right.add(self.json_box, text="  JSON  ")
        paned.add(right, weight=4)

        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(self, textvariable=self.status, foreground=MUTED, padding=(16, 2, 16, 8)).pack(fill="x")

    # -- Fetch (background thread keeps the GUI responsive) ---------------------
    def start_lookup(self):
        if self._busy:
            return
        self._busy = True
        self.btn.state(["disabled"])
        self.status.set("Lade …")
        query = self.entry.get()
        threading.Thread(target=self._worker, args=(query,), daemon=True).start()

    def _worker(self, query):
        try:
            result = lookup(query)
            self.after(0, self._done, result, None)
        except FhirError as e:
            self.after(0, self._done, None, e)

    def _done(self, result, error):
        self._busy = False
        self.btn.state(["!disabled"])
        if error:
            self.status.set(f"Error: {error}")
            return
        patients, info = result
        self.tree.delete(*self.tree.get_children())
        self.patients.clear()
        for p in patients:
            iid = self.tree.insert("", "end", text=display_name(p), values=(p.get("id", ""),))
            self.patients[iid] = p
        self.status.set(f"{info} - {len(patients)} result(s).")
        if patients:
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
        else:
            self._show_empty("No patients found.")

    # -- Anzeige ---------------------------------------------------------------
    def on_select(self, _):
        sel = self.tree.selection()
        if sel:
            self.show_patient(self.patients[sel[0]])

    def _set_json(self, data):
        self.json_box.configure(state="normal")
        self.json_box.delete("1.0", "end")
        if data is not None:
            self.json_box.insert("1.0", json.dumps(data, indent=2, ensure_ascii=False))
        self.json_box.configure(state="disabled")

    def show_patient(self, p: dict):
        self._set_json(p)
        self.profile.clear()
        parent = self.profile.inner

        # Kopfkarte
        top = tk.Frame(parent, bg=CARD, highlightbackground="#dfe3e8", highlightthickness=1)
        top.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(top, text=display_name(p), font=F_TITLE, bg=CARD, anchor="w").pack(fill="x", padx=14, pady=(10, 0))
        tk.Label(top, text=f"Patient/{p.get('id', '?')}", font=F_BASE, fg=MUTED, bg=CARD, anchor="w").pack(fill="x", padx=14)
        hints = conformity_hints(p)
        msg = "Required profile fields present ✓" if not hints else "Profile note: " + "; ".join(hints)
        tk.Label(top, text=msg, font=F_BASE, fg="#15803d" if not hints else "#b91c1c",
                 bg=CARD, anchor="w").pack(fill="x", padx=14, pady=(2, 10))

        for title, rows in build_sections(p):
            rows = [(k, v) for k, v in rows if v not in (None, "")]
            if rows:
                self._card(parent, title, rows)

    def _show_welcome(self):
        self._show_empty("Enter a patient ID or name, then press “Fetch”")

    def _show_empty(self, message):
        self.profile.clear()
        self._set_json(None)
        card = tk.Frame(self.profile.inner, bg=CARD, highlightbackground="#dfe3e8", highlightthickness=1)
        card.pack(fill="x", padx=8, pady=8)
        tk.Label(card, text=message, font=F_HEAD, fg=MUTED, bg=CARD,
                 anchor="w", justify="left", wraplength=700).pack(fill="x", padx=14, pady=18)

    def _card(self, parent, title, rows):
        card = tk.Frame(parent, bg=CARD, highlightbackground="#dfe3e8", highlightthickness=1)
        card.pack(fill="x", padx=8, pady=4)
        tk.Label(card, text=title, font=F_HEAD, fg=ACCENT, bg=CARD, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(8, 4))
        for r, (k, v) in enumerate(rows, 1):
            tk.Label(card, text=k, font=F_BASE, fg=MUTED, bg=CARD, anchor="nw", width=22).grid(
                row=r, column=0, sticky="nw", padx=(14, 6), pady=1)
            val = tk.Label(card, text=str(v), font=F_BOLD, bg=CARD, anchor="w", justify="left", wraplength=560)
            val.grid(row=r, column=1, sticky="w", pady=1)
        tk.Frame(card, bg=CARD, height=6).grid(row=len(rows) + 1, column=0)


if __name__ == "__main__":
    Chase().mainloop()