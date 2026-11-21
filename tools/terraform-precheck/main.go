// terraform-precheck is a static check for Terraform code. It needs NO credentials and must run BEFORE any
// `terraform init` or `terraform plan` that has cloud credentials in its environment.
//
// It rejects what allows code execution during `plan`, or redirecting or reading data:
//   - data sources and resources of providers that are not allowed (including the implicit ones: external, http, local, null, dns, ...)
//   - `required_providers` entries whose `source` is not in the allowed list
//   - modules that are not local paths inside the checked directory
//   - provisioners and connection blocks
//   - `terraform { cloud {} }`, `provider_meta`, and any `backend` other than azurerm with only a `key`
//   - `provider` blocks with attributes that could redirect credentials (endpoints, proxies, ...)
//   - built-in functions that read files of the runner (file, templatefile, fileset, ...) or strip the sensitive mark
//     (nonsensitive): they could print the environment, credential files or state secrets into the (public) log.
//     Function calls are found in the parsed expressions, so they are detected inside templates and nested expressions.
//   - *.tf.json files (rejected outright: this repository does not use them and they are harder to review)
//   - Terraform CLI configuration files (.terraformrc, terraform.rc, *.tfrc), committed .terraform/ directories and symlinks
//   - a missing .terraform.lock.hcl (warning) or one that differs from the one in main (warning, review by hand)
//
// Usage: terraform-precheck <terraform-directory> [--lock-base <lock file from main>] [--strict]
// Exit code: 0 if it passes; 1 if there are blocking findings; 2 if there are only warnings and --strict is set.
//
// IMPORTANT: run this program from the protected branch (main), never from the pull request code.
// Changing the allowed lists below requires a change merged into main.
package main

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/hashicorp/hcl/v2"
	"github.com/hashicorp/hcl/v2/hclsyntax"
)

var allowedProviderSources = set(
	"hashicorp/aws", "hashicorp/azuread", "hashicorp/azurerm", "hashicorp/google", "hashicorp/random",
	"hashicorp/tls", "alekc/kubectl", "betr-io/mssql", "integrations/github",
)

// Resource and data source type prefixes that map to the allowed providers.
var allowedTypePrefixes = set("aws", "azurerm", "azuread", "google", "random", "tls", "kubectl", "mssql", "github")

// Built-in resource types (provisioners are checked separately).
var builtinTypes = set("terraform_data")

// Attributes and blocks allowed in `provider` blocks. Anything else is rejected. The aws, google, azuread and github
// providers are configured through environment variables only: an `endpoints` block, `*_custom_endpoint`, a proxy,
// `metadata_host`... would redirect the job credentials to a server controlled by someone else.
var allowedProviderAttrs = map[string]map[string]bool{
	"azurerm": set("features", "key_vault", "purge_soft_delete_on_destroy"),
	"mssql":   set("debug"),
	"kubectl": set("client_certificate", "client_key", "cluster_ca_certificate", "host", "load_config_file"),
}

var allowedTopLevel = set("terraform", "provider", "resource", "data", "module", "variable", "output", "locals", "moved", "import", "removed", "check")

// Built-in functions that are never needed here and are dangerous with credentials in the environment.
var blockedFunctions = set("file", "templatefile", "filebase64", "filebase64sha256", "filebase64sha512", "filemd5",
	"filesha1", "filesha256", "filesha512", "fileexists", "fileset", "nonsensitive")

// Allowed backend type and the attributes allowed inside its block.
const expectedBackend = "azurerm"

var expectedBackendAttrs = set("key")

var findings, warnings []string

func set(v ...string) map[string]bool {
	m := make(map[string]bool, len(v))
	for _, s := range v {
		m[s] = true
	}
	return m
}

func bad(f, format string, a ...any)  { findings = append(findings, f+": "+fmt.Sprintf(format, a...)) }
func warn(f, format string, a ...any) { warnings = append(warnings, f+": "+fmt.Sprintf(format, a...)) }

func main() {
	var dir, lockBase string
	strict := false
	args := os.Args[1:]
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--strict":
			strict = true
		case "--lock-base":
			i++
			if i >= len(args) {
				usage()
			}
			lockBase = args[i]
		default:
			if dir != "" || strings.HasPrefix(args[i], "--") {
				usage()
			}
			dir = args[i]
		}
	}
	if dir == "" {
		usage()
	}
	root, err := filepath.Abs(dir)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if real, err := filepath.EvalSymlinks(root); err == nil {
		root = real
	}

	n := 0
	err = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(root, p)
		if d.Type()&fs.ModeSymlink != 0 {
			bad(rel, "symbolic links are not allowed")
			return nil
		}
		if d.IsDir() {
			if d.Name() == ".terraform" {
				bad(rel, ".terraform directory in the repository (it must not be committed)")
				return filepath.SkipDir
			}
			return nil
		}
		name := d.Name()
		switch {
		case name == ".terraformrc" || name == "terraform.rc" || strings.HasSuffix(name, ".tfrc"):
			bad(rel, "Terraform CLI configuration file (it can redirect providers)")
		case strings.HasSuffix(name, ".tf.json"):
			n++
			bad(rel, "*.tf.json files are not allowed")
		case strings.HasSuffix(name, ".tf"):
			n++
			checkFile(root, p, rel)
		}
		return nil
	})
	if err != nil {
		bad(".", "cannot walk the directory: %v", err)
	}

	lock := filepath.Join(root, ".terraform.lock.hcl")
	if cur, err := os.ReadFile(lock); err != nil {
		warn(".terraform.lock.hcl", "missing: provider hashes are not pinned (add it to the repository)")
	} else if base, err := os.ReadFile(lockBase); lockBase != "" && err == nil && !bytes.Equal(cur, base) {
		warn(".terraform.lock.hcl", "differs from the one in main: review it by hand")
	}

	fmt.Printf("[precheck] .tf files analysed: %d\n", n)
	sort.Strings(warnings)
	sort.Strings(findings)
	for _, w := range warnings {
		fmt.Println("  WARN ", w)
	}
	for _, f := range findings {
		fmt.Println("  BLOCK", f)
	}
	if len(findings) > 0 {
		fmt.Println("[precheck] RESULT: REJECTED")
		os.Exit(1)
	}
	if len(warnings) > 0 {
		fmt.Println("[precheck] RESULT: OK (with warnings)")
		if strict {
			os.Exit(2)
		}
		return
	}
	fmt.Println("[precheck] RESULT: OK")
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: terraform-precheck <terraform-directory> [--lock-base <lock file>] [--strict]")
	os.Exit(2)
}

func checkFile(root, path, rel string) {
	src, err := os.ReadFile(path)
	if err != nil {
		bad(rel, "cannot read file: %v", err)
		return
	}
	f, diags := hclsyntax.ParseConfig(src, rel, hcl.InitialPos)
	if diags.HasErrors() {
		bad(rel, "cannot be parsed: %s", diags.Error())
		return
	}
	body := f.Body.(*hclsyntax.Body)

	// Function calls anywhere in the file (templates and nested expressions included).
	_ = hclsyntax.VisitAll(body, func(node hclsyntax.Node) hcl.Diagnostics {
		if call, ok := node.(*hclsyntax.FunctionCallExpr); ok && blockedFunctions[call.Name] {
			bad(rel, "call to '%s()' is not allowed (it can read runner files or reveal sensitive values)", call.Name)
		}
		return nil
	})

	for _, attr := range body.Attributes {
		bad(rel, "top-level attribute '%s' is not allowed", attr.Name)
	}
	for _, b := range body.Blocks {
		if !allowedTopLevel[b.Type] {
			bad(rel, "top-level block '%s' is not allowed", b.Type)
			continue
		}
		switch b.Type {
		case "terraform":
			checkTerraform(rel, b)
		case "provider":
			checkProvider(rel, b)
		case "resource", "data":
			checkResource(rel, b)
		case "module":
			checkModule(root, path, rel, b)
		}
	}
}

func checkTerraform(rel string, b *hclsyntax.Block) {
	for _, sub := range b.Body.Blocks {
		switch sub.Type {
		case "required_providers":
			for name, attr := range sub.Body.Attributes {
				checkRequiredProvider(rel, name, attr)
			}
		case "backend":
			typ := ""
			if len(sub.Labels) > 0 {
				typ = sub.Labels[0]
			}
			attrs := attrNames(sub.Body)
			if typ != expectedBackend || len(sub.Body.Blocks) > 0 || !subset(attrs, expectedBackendAttrs) {
				bad(rel, "backend block changed (type '%s', attributes %v)", typ, attrs)
			}
		case "cloud", "provider_meta":
			bad(rel, "terraform block '%s' is not allowed", sub.Type)
		}
	}
}

func checkRequiredProvider(rel, name string, attr *hclsyntax.Attribute) {
	val, diags := attr.Expr.Value(nil)
	if diags.HasErrors() {
		bad(rel, "required_providers.%s cannot be evaluated statically", name)
		return
	}
	source := "hashicorp/" + name // legacy string form: the version constraint only
	if val.Type().IsObjectType() {
		if val.Type().HasAttribute("source") {
			s := val.GetAttr("source")
			if !s.IsKnown() || s.IsNull() {
				bad(rel, "required_providers.%s has an invalid source", name)
				return
			}
			source = s.AsString()
		}
	}
	if !allowedProviderSources[strings.ToLower(source)] {
		bad(rel, "provider source not allowed: %s", source)
	}
}

func checkProvider(rel string, b *hclsyntax.Block) {
	name := ""
	if len(b.Labels) > 0 {
		name = b.Labels[0]
	}
	allowed, ok := allowedProviderAttrs[name]
	if !ok {
		bad(rel, "provider block '%s' is not allowed (only %v)", name, keys(allowedProviderAttrs))
		return
	}
	attrs := attrNames(b.Body)
	delete(attrs, "alias")
	if !subset(attrs, allowed) {
		bad(rel, "provider '%s' has attributes or blocks that are not allowed: %v", name, difference(attrs, allowed))
	}
	if name == "kubectl" {
		if h, ok := b.Body.Attributes["host"]; ok && len(h.Expr.Variables()) == 0 {
			bad(rel, "kubectl provider with a literal host (it must come from a module or resource)")
		}
	}
}

func checkResource(rel string, b *hclsyntax.Block) {
	typ := ""
	if len(b.Labels) > 0 {
		typ = b.Labels[0]
	}
	if !builtinTypes[typ] {
		prefix, _, _ := strings.Cut(typ, "_")
		if !allowedTypePrefixes[prefix] {
			bad(rel, "type '%s' belongs to a provider that is not allowed (prefix '%s')", typ, prefix)
		}
	}
	for _, sub := range b.Body.Blocks {
		if sub.Type == "provisioner" || sub.Type == "connection" {
			bad(rel, "%s block used in '%s' (provisioners run arbitrary commands)", sub.Type, typ)
		}
	}
}

func checkModule(root, path, rel string, b *hclsyntax.Block) {
	attr, ok := b.Body.Attributes["source"]
	if !ok {
		bad(rel, "module %v has no source", b.Labels)
		return
	}
	val, diags := attr.Expr.Value(nil)
	if diags.HasErrors() || !val.IsKnown() || val.IsNull() || !val.Type().Equals(stringType()) {
		bad(rel, "module %v has a source that is not a literal string", b.Labels)
		return
	}
	src := val.AsString()
	if !strings.HasPrefix(src, "./") && !strings.HasPrefix(src, "../") {
		bad(rel, "module with a non-local source: %s", src)
		return
	}
	target := filepath.Join(filepath.Dir(path), src)
	if real, err := filepath.EvalSymlinks(target); err == nil {
		target = real
	}
	if target != root && !strings.HasPrefix(target, root+string(os.PathSeparator)) {
		bad(rel, "module outside the checked directory: %s", src)
	}
}

func attrNames(b *hclsyntax.Body) map[string]bool {
	m := map[string]bool{}
	for n := range b.Attributes {
		m[n] = true
	}
	for _, blk := range b.Blocks {
		m[blk.Type] = true
	}
	return m
}

func subset(a, b map[string]bool) bool { return len(difference(a, b)) == 0 }

func difference(a, b map[string]bool) []string {
	var d []string
	for k := range a {
		if !b[k] {
			d = append(d, k)
		}
	}
	sort.Strings(d)
	return d
}

func keys[V any](m map[string]V) []string {
	var k []string
	for n := range m {
		k = append(k, n)
	}
	sort.Strings(k)
	return k
}
