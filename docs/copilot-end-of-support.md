---
title: AWS Copilot CLI end of support (deprecated) — what to do now
description: >-
  The AWS Copilot CLI reached end of support on 2026-06-12 and its repository was archived on
  2026-06-22. What still works, what breaks next, and your four migration options compared:
  keep CloudFormation, ECS Express Mode, CDK, or Terraform with ecsodus.
---

# AWS Copilot CLI end of support: what to do now

The **AWS Copilot CLI is deprecated.** AWS ended support on **2026-06-12** and archived the
[aws/copilot-cli](https://github.com/aws/copilot-cli) repository on **2026-06-22**. It gets no
new features and no security fixes
([AWS announcement](https://aws.amazon.com/blogs/containers/announcing-the-end-of-support-for-the-aws-copilot-cli)).

## Does my Copilot app stop working?

**No.** Everything Copilot deployed is ordinary AWS infrastructure (ECS services, load balancers,
VPCs, databases) managed by **CloudFormation stacks**, and those keep running. What you lose is
the tool that manages them:

- **No fixes.** New AWS features, API changes and bugs in the CLI will not be fixed.
- **Lambda runtime deadlines.** Copilot's custom-resource Lambdas run on **`nodejs20.x`**. AWS
  blocks *creating* functions on that runtime from **2027-07-29**, and *updating* them from
  **2027-08-31**. After those dates, a stack operation that needs to recreate or update those
  functions will fail.

## Your options

| Option | Traffic moves? | Ends on | Effort | Risk |
|---|---|---|---|---|
| **Keep the CloudFormation** and deploy with `aws cloudformation deploy` plus a deploy tool such as [ecspresso](https://github.com/kayac/ecspresso) | No | CloudFormation | Low | Lowest until the 2027 Lambda deadlines |
| **Rebuild on ECS Express Mode** (AWS's recommendation) | Yes, a cutover | Express Mode, which can be managed by Terraform | Medium | Cutover plus moving stateful data yourself |
| **Rebuild with CDK L3 constructs** | Yes, a cutover | CDK | Medium–high | The same cutover risks |
| **Adopt in place into Terraform with [ecsodus](index.md)** | **No** | Terraform | Low–medium | Gated and verified on AWS; read the [verified scope](STATUS.md) |

If you don't need Terraform, keeping the CloudFormation is the zero-risk choice. Every ecsodus
report says so first.

## The trap in "just delete the Copilot stacks"

Deleting a healthy CloudFormation stack deletes every resource without
`DeletionPolicy: Retain`, and Copilot sets Retain almost nowhere. Its custom resources also act
on delete. The [env-controller](knowledge/copilot-custom-resources.md) removes the shared load
balancer, NAT gateways and EFS file system once no service uses them. ecsodus exists to make that
step safe: [how the migration works](migrate-copilot-to-terraform.md).

## App Runner and Proton

- **App Runner** closed to new customers on 2026-04-30. Existing services keep running. ecsodus
  support is planned for v0.2.
- **AWS Proton** reaches end of support on 2026-10-07. Its provisioned stacks remain ordinary
  CloudFormation.
