package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func run(t *testing.T, content string) []string {
	t.Helper()
	root := t.TempDir()
	p := filepath.Join(root, "main.tf")
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	findings = nil
	checkFile(root, p, "main.tf")
	return findings
}

func TestAccepted(t *testing.T) {
	ok := map[string]string{
		"resource":       `resource "aws_s3_bucket" "b" { bucket = "x" }`,
		"data":           `data "google_project" "p" {}`,
		"terraform_data": `resource "terraform_data" "x" { input = 1 }`,
		"module":         `module "m" { source = "./modules/m" }`,
		"backend":        "terraform {\n backend \"azurerm\" {\n key = \"k\"\n }\n}",
		"providers": `terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "5.84.0" }
    kubectl = { source = "alekc/kubectl", version = "2.1.3" }
  }
}`,
		"provider": `provider "azurerm" {
  features {}
}`,
		"kubectl":   `provider "kubectl" { host = module.x.host }`,
		"lookalike": `locals { a = "file(" }`, // a string that merely contains the text
	}
	for name, c := range ok {
		if f := run(t, c); len(f) != 0 {
			t.Errorf("%s: unexpected findings %v", name, f)
		}
	}
}

func TestRejected(t *testing.T) {
	bad := map[string]string{
		"external":         `data "external" "x" { program = ["sh"] }`,
		"http":             `data "http" "x" { url = "https://e.example" }`,
		"local_file":       `resource "local_file" "x" { filename = "a" }`,
		"null":             `resource "null_resource" "x" {}`,
		"remote_state":     `data "terraform_remote_state" "x" { backend = "local" }`,
		"provisioner":      "resource \"aws_s3_bucket\" \"b\" {\n provisioner \"local-exec\" {\n command = \"id\"\n }\n}",
		"connection":       "resource \"aws_s3_bucket\" \"b\" {\n connection {\n host = \"x\"\n }\n}",
		"provider src":     "terraform {\n required_providers {\n x = { source = \"evil/x\" }\n }\n}",
		"legacy provider":  "terraform {\n required_providers {\n evil = \"1.0\"\n }\n}",
		"git module":       `module "m" { source = "git::https://e.example/m.git" }`,
		"registry module":  `module "m" { source = "terraform-aws-modules/vpc/aws" }`,
		"escaping module":  `module "m" { source = "../../../etc" }`,
		"dynamic module":   `module "m" { source = var.s }`,
		"backend type":     "terraform {\n backend \"http\" {\n address = \"https://e.example\"\n }\n}",
		"backend attr":     "terraform {\n backend \"azurerm\" {\n key = \"k\"\n storage_account_name = \"x\"\n }\n}",
		"cloud":            "terraform {\n cloud {\n organization = \"x\"\n }\n}",
		"aws endpoints":    "provider \"aws\" {\n endpoints {\n sts = \"https://e.example\"\n }\n}",
		"azurerm host":     "provider \"azurerm\" {\n metadata_host = \"e.example\"\n features {}\n}",
		"github provider":  `provider "github" { base_url = "https://e.example" }`,
		"kubectl host":     `provider "kubectl" { host = "https://e.example" }`,
		"file":             `locals { a = file("/proc/self/environ") }`,
		"file in template": `locals { a = "x-${file("/proc/self/environ")}" }`,
		"nested file":      `output "o" { value = base64encode(templatefile("a", {})) }`,
		"fileset":          `locals { a = fileset("/", "*") }`,
		"nonsensitive":     `output "o" { value = nonsensitive(var.x) }`,
		"filebase64":       `locals { a = filebase64("/etc/passwd") }`,
		"unknown block":    `foo "x" {}`,
		"top attr":         `a = 1`,
		"syntax error":     `resource "aws_s3_bucket" {`,
	}
	for name, c := range bad {
		f := run(t, c)
		if len(f) == 0 {
			t.Errorf("%s: expected findings, got none", name)
		}
		for _, x := range f {
			if strings.Contains(x, "cannot be parsed") && name != "syntax error" {
				t.Errorf("%s: test input does not parse (it would pass for the wrong reason): %s", name, x)
			}
		}
	}
}
