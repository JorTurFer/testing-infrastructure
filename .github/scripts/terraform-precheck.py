#!/usr/bin/env python3
"""
Static Terraform pre-check. It needs NO credentials and must run BEFORE any `terraform init` or `terraform plan`.

It rejects what allows code execution during `plan`, or redirecting or reading data:
  - data sources and resources of providers that are not allowed (including the implicit ones: external, http, local, null, dns, ...)
  - `required_providers` entries whose `source` is not in the allowed list
  - modules that are not local paths inside the repository
  - provisioners (local-exec, remote-exec, file)
  - changes to the `backend` block (only azurerm with the expected attributes is accepted)
  - `provider` blocks with attributes that could redirect credentials (endpoints, proxies, ...)
  - built-in functions that read files of the runner (file, templatefile, filebase64, fileset, ...): they could print the
    environment or credential files into the (public) log without using any provider
  - `nonsensitive()`, which strips the sensitive mark and could print secrets that live in the state into the log
  - *.tf.json files (Terraform loads them too, so they are parsed as JSON)
  - Terraform CLI configuration files (.terraformrc, terraform.rc) and committed .terraform/ directories
  - a missing .terraform.lock.hcl (warning) or a lock file that differs from the one in main (warning, review by hand)

Usage:  terraform-precheck.py <terraform-directory> [--lock-base <lock file from main>] [--strict]
Exit code: 0 if it passes; 1 if there are blocking findings; 2 if there are only warnings and --strict is set.

IMPORTANT: run this script from the protected branch (main), never from the pull request code.
Changing the allowed lists below requires a change merged into main.
"""
import json, os, re, sys

ALLOWED_PROVIDER_SOURCES = {
    "hashicorp/aws", "hashicorp/azuread", "hashicorp/azurerm", "hashicorp/google", "hashicorp/random",
    "hashicorp/tls", "alekc/kubectl", "betr-io/mssql", "integrations/github",
}
# Resource/data type prefixes that map to the allowed providers.
ALLOWED_TYPE_PREFIXES = {"aws", "azurerm", "azuread", "google", "random", "tls", "kubectl", "mssql", "github"}
BUILTIN_TYPES = {"terraform_data"}  # built in; provisioners are checked separately
# Attributes allowed in `provider` blocks (taken from the code in main on 2026-11-21). Anything else is rejected.
ALLOWED_PROVIDER_ATTRS = {
    "azurerm": {"features", "key_vault", "purge_soft_delete_on_destroy"},
    "mssql": {"debug"},
    "kubectl": {"client_certificate", "client_key", "cluster_ca_certificate", "host", "load_config_file"},
}
# Built-in functions that are never needed here and are dangerous with credentials in the environment.
# They are searched in the raw text (strings included) because they also work inside `${...}` interpolations.
BLOCKED_FUNCTIONS = ("file", "templatefile", "filebase64", "filebase64sha256", "filebase64sha512", "filemd5", "filesha1",
                     "filesha256", "filesha512", "fileexists", "fileset", "nonsensitive")
BLOCKED_FUNCTIONS_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(BLOCKED_FUNCTIONS) + r")\s*\(")
EXPECTED_BACKEND = ("azurerm", {"key"})  # allowed backend type and attributes inside the block

findings, warnings = [], []
def bad(f, msg): findings.append(f"{f}: {msg}")
def warn(f, msg): warnings.append(f"{f}: {msg}")

def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"(?m)(^|\s)(#|//).*$", "", s)

def blocks(s, kind):
    """Return (header, body) for each `kind "x" "y" { ... }` block, with balanced braces."""
    out = []
    for m in re.finditer(rf"(?m)^\s*{kind}\s*((?:\"[^\"]*\"\s*)*)\{{", s):
        i, depth = m.end(), 1
        while i < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[i], 0); i += 1
        out.append((m.group(1).strip(), s[m.end():i - 1]))
    return out

def check_hcl(path, rel, text):
    t = strip_comments(text)
    for m in BLOCKED_FUNCTIONS_RE.finditer(t):
        bad(rel, f"call to '{m.group(1)}()' is not allowed (it can read runner files or reveal sensitive values)")
    for hdr, body in blocks(t, "data") + blocks(t, "resource"):
        typ = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        pref = typ.split("_")[0]
        if typ in BUILTIN_TYPES: continue
        if pref not in ALLOWED_TYPE_PREFIXES:
            bad(rel, f"type '{typ}' belongs to a provider that is not allowed (prefix '{pref}')")
    if re.search(r"(?m)^\s*provisioner\s+\"", t) or re.search(r"\bprovisioner\s+\"(local-exec|remote-exec|file)\"", t):
        bad(rel, "provisioner used (it runs arbitrary commands)")
    for hdr, body in blocks(t, "required_providers") + [("", b) for _, b in blocks(t, "terraform")]:
        for m in re.finditer(r"source\s*=\s*\"([^\"]+)\"", body):
            src = m.group(1).lower()
            if src not in ALLOWED_PROVIDER_SOURCES and not src.startswith("./"):
                # it only counts as a provider if it is inside required_providers
                if re.search(r"required_providers", t): bad(rel, f"provider source not allowed: {m.group(1)}")
    for hdr, body in blocks(t, "module"):
        m = re.search(r"(?m)^\s*source\s*=\s*\"([^\"]+)\"", body)
        if not m: bad(rel, f"module {hdr} has no source"); continue
        src = m.group(1)
        norm = os.path.normpath(os.path.join(os.path.dirname(path), src))
        if not (src.startswith("./") or src.startswith("../")):
            bad(rel, f"module with a non-local source: {src}")
        elif not os.path.realpath(norm).startswith(os.path.realpath(ROOT) + os.sep):
            bad(rel, f"module outside the repository: {src}")
    # `provider` blocks: strict allowlist of names and attributes. aws, google, azuread and github are
    # configured through environment variables; an `endpoints` block, `*_custom_endpoint`, a proxy, `metadata_host`...
    # would redirect the job credentials to a server controlled by someone else.
    for hdr, body in blocks(t, "provider"):
        pname = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        attrs = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\{)", body)) - {"alias"}
        allowed = ALLOWED_PROVIDER_ATTRS.get(pname)
        if allowed is None:
            bad(rel, f"provider block '{pname}' is not allowed (only {sorted(ALLOWED_PROVIDER_ATTRS)})")
        elif not attrs <= allowed:
            bad(rel, f"provider '{pname}' has attributes that are not allowed: {sorted(attrs - allowed)}")
        elif pname == "kubectl":
            m = re.search(r"(?m)^\s*host\s*=\s*(.+)$", body)
            if m and m.group(1).strip().startswith('"'): bad(rel, "kubectl provider with a literal host (it must come from a module or resource)")
    for hdr, body in blocks(t, "backend"):
        typ = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        attrs = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", body))
        if typ != EXPECTED_BACKEND[0] or not attrs <= EXPECTED_BACKEND[1]:
            bad(rel, f"backend block changed (type '{typ}', attributes {sorted(attrs)})")

def check_json(rel, text):
    for m in BLOCKED_FUNCTIONS_RE.finditer(text):
        bad(rel, f"call to '{m.group(1)}()' is not allowed in .tf.json")
    try: j = json.loads(text)
    except Exception: bad(rel, "Terraform JSON file cannot be parsed"); return
    for kind in ("data", "resource"):
        for typ in (j.get(kind) or {}):
            pref = typ.split("_")[0]
            if typ not in BUILTIN_TYPES and pref not in ALLOWED_TYPE_PREFIXES: bad(rel, f"type '{typ}' not allowed ({kind})")
    if "provisioner" in json.dumps(j): bad(rel, "provisioner in .tf.json")
    for m in re.finditer(r"\"source\"\s*:\s*\"([^\"]+)\"", text):
        s = m.group(1)
        if not (s.startswith("./") or s.startswith("../")) and s.lower() not in ALLOWED_PROVIDER_SOURCES:
            bad(rel, f"source not allowed in .tf.json: {s}")
    if "backend" in (j.get("terraform") or {}) if isinstance(j.get("terraform"), dict) else False:
        bad(rel, "backend in .tf.json")

def main():
    global ROOT
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    ROOT = os.path.abspath(sys.argv[1]); strict = "--strict" in sys.argv
    lock_base = sys.argv[sys.argv.index("--lock-base") + 1] if "--lock-base" in sys.argv else None
    n = 0
    for dp, dns, fns in os.walk(ROOT):
        if ".terraform" in dns:
            bad(os.path.relpath(dp, ROOT) + "/.terraform", ".terraform directory in the repository (it must not be committed)"); dns.remove(".terraform")
        for fn in fns:
            p = os.path.join(dp, fn); rel = os.path.relpath(p, ROOT)
            if fn in (".terraformrc", "terraform.rc") or fn.endswith(".tfrc"): bad(rel, "Terraform CLI configuration file (it can redirect providers)")
            if fn.endswith(".tf"): n += 1; check_hcl(p, rel, open(p, errors="replace").read())
            elif fn.endswith(".tf.json"): n += 1; check_json(rel, open(p, errors="replace").read())
    lock = os.path.join(ROOT, ".terraform.lock.hcl")
    if not os.path.exists(lock): warn(".terraform.lock.hcl", "missing: provider hashes are not pinned (add it to the repository)")
    elif lock_base and os.path.exists(lock_base) and open(lock).read() != open(lock_base).read(): warn(".terraform.lock.hcl", "differs from the one in main: review it by hand")
    print(f"[precheck] .tf/.tf.json files analysed: {n}")
    for w in warnings: print("  WARN ", w)
    for f in findings: print("  BLOCK", f)
    if findings: print("[precheck] RESULT: REJECTED"); sys.exit(1)
    print("[precheck] RESULT: OK" + (" (with warnings)" if warnings else "")); sys.exit(2 if (warnings and strict) else 0)
main()
