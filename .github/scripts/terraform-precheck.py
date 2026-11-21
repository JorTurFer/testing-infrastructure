#!/usr/bin/env python3
"""
Pre-check estático de Terraform, SIN credenciales, para ejecutar ANTES de cualquier `terraform init/plan`.
Rechaza lo que permite ejecutar código durante `plan` o redirigir/leer datos:
  - data/resource de proveedores no permitidos (incluye los implícitos: external, http, local, null, dns, ...)
  - required_providers con `source` fuera de la lista permitida
  - módulos que no sean rutas locales dentro del repo
  - provisioners (local-exec, remote-exec, file)
  - cambios en el bloque `backend` (solo se admite azurerm con la clave esperada)
  - ficheros *.tf.json (Terraform también los carga; se parsean como JSON)
  - ficheros de configuración de CLI (.terraformrc, terraform.rc) y directorios .terraform/
  - ausencia de .terraform.lock.hcl (aviso) o cambios en él (se señala para revisión)
Uso:  terraform-precheck.py <directorio-terraform> [--lock-base <fichero lock de main>]
Salida: código 0 si pasa; 1 si hay hallazgos que bloquean; 2 si solo hay avisos con --strict.
IMPORTANTE: este script debe ejecutarse desde la rama protegida (main), no desde el código de la PR.
"""
import json, os, re, sys

ALLOWED_PROVIDER_SOURCES = {
    "hashicorp/aws", "hashicorp/azuread", "hashicorp/azurerm", "hashicorp/google", "hashicorp/random",
    "hashicorp/tls", "alekc/kubectl", "betr-io/mssql", "grafana/grafana", "integrations/github",
}
# prefijo del tipo de recurso -> proveedor esperado
ALLOWED_TYPE_PREFIXES = {"aws", "azurerm", "azuread", "google", "random", "tls", "kubectl", "mssql", "grafana", "github"}
BUILTIN_TYPES = {"terraform_data"}  # sin provisioners (se vigilan aparte)
# Atributos permitidos en bloques `provider` (derivados del código de main el 21/11/2026). Cualquier otro se rechaza.
ALLOWED_PROVIDER_ATTRS = {
    "azurerm": {"features", "key_vault", "purge_soft_delete_on_destroy"},
    "mssql": {"debug"},
    "kubectl": {"client_certificate", "client_key", "cluster_ca_certificate", "host", "load_config_file"},
}
EXPECTED_BACKEND = ("azurerm", {"key"})  # tipo y atributos permitidos dentro del bloque

findings, warnings = [], []
def bad(f, msg): findings.append(f"{f}: {msg}")
def warn(f, msg): warnings.append(f"{f}: {msg}")

def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"(?m)(^|\s)(#|//).*$", "", s)

def blocks(s, kind):
    """Devuelve (cabecera, cuerpo) de bloques `kind "x" "y" { ... }` con llaves balanceadas."""
    out = []
    for m in re.finditer(rf"(?m)^\s*{kind}\s*((?:\"[^\"]*\"\s*)*)\{{", s):
        i, depth = m.end(), 1
        while i < len(s) and depth:
            depth += {"{": 1, "}": -1}.get(s[i], 0); i += 1
        out.append((m.group(1).strip(), s[m.end():i - 1]))
    return out

def check_hcl(path, rel, text):
    t = strip_comments(text)
    for hdr, body in blocks(t, "data") + blocks(t, "resource"):
        typ = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        pref = typ.split("_")[0]
        if typ in BUILTIN_TYPES: continue
        if pref not in ALLOWED_TYPE_PREFIXES:
            bad(rel, f"tipo '{typ}' de un proveedor no permitido (prefijo '{pref}')")
    if re.search(r"(?m)^\s*provisioner\s+\"", t) or re.search(r"\bprovisioner\s+\"(local-exec|remote-exec|file)\"", t):
        bad(rel, "uso de provisioner (ejecuta comandos arbitrarios)")
    for hdr, body in blocks(t, "required_providers") + [("", b) for _, b in blocks(t, "terraform")]:
        for m in re.finditer(r"source\s*=\s*\"([^\"]+)\"", body):
            src = m.group(1).lower()
            if src not in ALLOWED_PROVIDER_SOURCES and not src.startswith("./"):
                # solo cuenta como proveedor si está dentro de required_providers
                if re.search(r"required_providers", t): bad(rel, f"provider con source no permitido: {m.group(1)}")
    for hdr, body in blocks(t, "module"):
        m = re.search(r"(?m)^\s*source\s*=\s*\"([^\"]+)\"", body)
        if not m: bad(rel, f"módulo {hdr} sin source"); continue
        src = m.group(1)
        norm = os.path.normpath(os.path.join(os.path.dirname(path), src))
        if not (src.startswith("./") or src.startswith("../")):
            bad(rel, f"módulo con source no local: {src}")
        elif not os.path.realpath(norm).startswith(os.path.realpath(ROOT) + os.sep):
            bad(rel, f"módulo fuera del repositorio: {src}")
    # Bloques provider: lista permitida estricta de nombres y atributos (aws/google/azuread/github/grafana se
    # configuran por variables de entorno; un `endpoints`, `*_custom_endpoint`, proxy, `metadata_host`... redirigiría
    # las credenciales del job a un servidor ajeno).
    for hdr, body in blocks(t, "provider"):
        pname = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        attrs = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|\{)", body)) - {"alias"}
        allowed = ALLOWED_PROVIDER_ATTRS.get(pname)
        if allowed is None:
            bad(rel, f"bloque provider '{pname}' no permitido (solo {sorted(ALLOWED_PROVIDER_ATTRS)})")
        elif not attrs <= allowed:
            bad(rel, f"provider '{pname}' con atributos no permitidos: {sorted(attrs - allowed)}")
        elif pname == "kubectl":
            m = re.search(r"(?m)^\s*host\s*=\s*(.+)$", body)
            if m and m.group(1).strip().startswith('"'): bad(rel, "provider kubectl con host literal (debe venir de un módulo/recurso)")
    for hdr, body in blocks(t, "backend"):
        typ = (re.findall(r"\"([^\"]*)\"", hdr) or [""])[0]
        attrs = set(re.findall(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", body))
        if typ != EXPECTED_BACKEND[0] or not attrs <= EXPECTED_BACKEND[1]:
            bad(rel, f"bloque backend modificado (tipo '{typ}', atributos {sorted(attrs)})")

def check_json(rel, text):
    try: j = json.loads(text)
    except Exception: bad(rel, "JSON de Terraform no analizable"); return
    for kind in ("data", "resource"):
        for typ in (j.get(kind) or {}):
            pref = typ.split("_")[0]
            if typ not in BUILTIN_TYPES and pref not in ALLOWED_TYPE_PREFIXES: bad(rel, f"tipo '{typ}' no permitido ({kind})")
    if "provisioner" in json.dumps(j): bad(rel, "provisioner en .tf.json")
    for m in re.finditer(r"\"source\"\s*:\s*\"([^\"]+)\"", text):
        s = m.group(1)
        if not (s.startswith("./") or s.startswith("../")) and s.lower() not in ALLOWED_PROVIDER_SOURCES:
            bad(rel, f"source no permitido en .tf.json: {s}")
    if "backend" in (j.get("terraform") or {}) if isinstance(j.get("terraform"), dict) else False:
        bad(rel, "backend en .tf.json")

def main():
    global ROOT
    if len(sys.argv) < 2: print(__doc__); sys.exit(2)
    ROOT = os.path.abspath(sys.argv[1]); strict = "--strict" in sys.argv
    lock_base = sys.argv[sys.argv.index("--lock-base") + 1] if "--lock-base" in sys.argv else None
    n = 0
    for dp, dns, fns in os.walk(ROOT):
        if ".terraform" in dns:
            bad(os.path.relpath(dp, ROOT) + "/.terraform", "directorio .terraform en el repo (no debe estar versionado)"); dns.remove(".terraform")
        for fn in fns:
            p = os.path.join(dp, fn); rel = os.path.relpath(p, ROOT)
            if fn in (".terraformrc", "terraform.rc") or fn.endswith(".tfrc"): bad(rel, "fichero de configuración del CLI de Terraform (puede redirigir providers)")
            if fn.endswith(".tf"): n += 1; check_hcl(p, rel, open(p, errors="replace").read())
            elif fn.endswith(".tf.json"): n += 1; check_json(rel, open(p, errors="replace").read())
    lock = os.path.join(ROOT, ".terraform.lock.hcl")
    if not os.path.exists(lock): warn(".terraform.lock.hcl", "no existe: los hashes de los providers no están fijados (añadirlo al repo)")
    elif lock_base and os.path.exists(lock_base) and open(lock).read() != open(lock_base).read(): warn(".terraform.lock.hcl", "difiere del de main: revisar a mano")
    print(f"[precheck] ficheros .tf/.tf.json analizados: {n}")
    for w in warnings: print("  AVISO   ", w)
    for f in findings: print("  BLOQUEA ", f)
    if findings: print("[precheck] RESULTADO: RECHAZADO"); sys.exit(1)
    print("[precheck] RESULTADO: OK" + (" (con avisos)" if warnings else "")); sys.exit(2 if (warnings and strict) else 0)
main()
