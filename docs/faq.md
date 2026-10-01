---
title: AWS Copilot deprecated — FAQ (migration, Terraform, data safety)
description: >-
  Answers for teams still on the deprecated AWS Copilot CLI: is it safe to keep running, how to
  move to Terraform without downtime, what deleting Copilot stacks destroys, and how ecsodus
  compares with ECS Express Mode, CDK and cf2tf.
---

# AWS Copilot deprecated: FAQ

## Is AWS Copilot CLI deprecated?
Yes. AWS ended support on 2026-06-12 and archived the repository on 2026-06-22. See
[end of support](copilot-end-of-support.md).

## Will my Copilot services stop running?
No. They are CloudFormation stacks and keep running. Two dates matter for Copilot's
custom-resource Lambdas, which run on `nodejs20.x`: creating them is blocked from 2027-07-29, and
updating them from 2027-08-31.

## Can I just delete the Copilot CloudFormation stacks after importing into Terraform?
Not safely without preparation. A normal stack delete removes every resource without
`DeletionPolicy: Retain`, and Copilot's custom resources delete certificates, DNS records and
bucket contents. Deleting the last service stack also makes the env-controller remove the shared
load balancer, NAT gateways and EFS. ecsodus retain-patches every stack first. On AWS this
stopped every Delete handler from running ([evidence](e2e/2026-09-30-aws-e2e.md)).

## Why doesn't `delete-stack --retain-resources` work?
It only applies to stacks already in `DELETE_FAILED`. On a healthy stack the first delete
removes everything.

## Does ecsodus change anything in my AWS account?
No. ecsodus only reads: its AWS clients refuse every call that isn't
`Describe`/`List`/`Get`/`Lookup`. You run the generated runbook yourself, and each mutating step
in it is gated by an `ecsodus check`.

## Will the migration cause downtime?
Adopt-in-place moves no traffic. The same ECS service, load balancer and VPC keep serving, and
only the owner changes from CloudFormation to Terraform. In the AWS end-to-end run the service
answered HTTP 200 throughout.

## How is this different from cf2tf or `terraform plan -generate-config-out`?
Those convert templates or generate starting-point configuration. ecsodus produces HCL with the
exact deployed values, so the first plan is a pure import. It also handles the parts that make
Copilot dangerous to tear down: retain patches, custom-resource handlers, nested addon stacks,
the app StackSet, and teardown order.

## Should I use ECS Express Mode instead?
Express Mode is AWS's recommended destination for new deployments, and it can be managed by
Terraform. It is a rebuild, though: traffic moves, and you migrate stateful resources yourself.
ecsodus keeps what you already run, and its report tells you whether each service would fit
Express Mode later.

## Is this related to GitHub Copilot?
No. This is the **AWS Copilot CLI**, Amazon's tool for deploying containers to ECS and App Runner.

## What about AWS App Runner and Proton?
App Runner closed to new customers on 2026-04-30. Support for it is planned for v0.2. Proton
reaches end of support on 2026-10-07.
