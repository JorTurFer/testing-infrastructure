data "aws_caller_identity" "current" {}

locals {
  oidc_provider_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

// Keyless role of the Garbage Collector workflow. The role and the policy names start with `keda-` and `e2e-test-` so that the
// identity that applies Terraform is allowed to manage them.

resource "aws_iam_role" "cleanup" {
  name                 = "keda-e2e-cleanup"
  max_session_duration = 3600
  tags                 = var.tags

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:environment:${var.github_environment}"
        }
      }
    }]
  })
}

resource "aws_iam_policy" "cleanup" {
  name = "e2e-test-cleanup"
  tags = var.tags

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "aps:ListWorkspaces", "aps:DescribeWorkspace", "aps:DeleteWorkspace", "aps:ListTagsForResource",
        "dynamodb:ListTables", "dynamodb:DescribeTable", "dynamodb:DeleteTable", "dynamodb:ListTagsOfResource",
        "kinesis:ListStreams", "kinesis:DescribeStreamSummary", "kinesis:DeleteStream", "kinesis:ListTagsForStream",
        "sqs:ListQueues", "sqs:GetQueueAttributes", "sqs:DeleteQueue", "sqs:ListQueueTags",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cleanup" {
  role       = aws_iam_role.cleanup.name
  policy_arn = aws_iam_policy.cleanup.arn
}
