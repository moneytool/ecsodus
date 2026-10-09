---
title: Custom-domain AWS run, runbook draft (issue #6)
description: >-
  Draft procedure for the real AWS run that answers PLAN §6 question 4: a Copilot app with a
  delegated test domain, an ACM certificate and alias records, migrated with ecsodus and torn
  down, with measurements proving no DNS or certificate Delete handler ran.
---

# Custom-domain AWS run: runbook draft (issue #6)

**Draft, not yet run.** It needs the maintainer's explicit approval before anything billable
starts, the same as the 2026-09-30 and 2026-10-07 runs. It answers PLAN §6 question 4 ("Does
the shared ACM validation CNAME survive?") and the risks in the
[gap analysis](custom-domain-gap-analysis.md) (R1 to R4).

Conventions: run every snippet in one **bash** session (`bash -l`; the helpers use bash
indirection such as `${!z}`, which zsh does not support). Placeholders:

| Placeholder | Meaning |
|---|---|
| `<DOMAIN>` | a domain the maintainer owns, for example `example.org` |
| `ROOT=ecsodus-test.<DOMAIN>` | the delegated test subdomain. Copilot treats it as the app's root domain |
| `APP=ecsodus-e2e3`, `ENV=test` | Copilot names |
| `COPILOT=/path/to/copilot-v1.34.1` | the official v1.34.1 release binary, md5 verified as in earlier runs |
| `AWS_PROFILE=<sandbox>`, `AWS_REGION=us-east-1` | the sandbox member account |

```sh
export ROOT=ecsodus-test.<DOMAIN> APP=ecsodus-e2e3 ENV=test
export COPILOT=/path/to/copilot-v1.34.1 AWS_PROFILE=<sandbox> AWS_REGION=us-east-1
export TF_PLUGIN_CACHE_DIR=~/.cache/ecsodus-tf-plugins
mkdir -p ~/e2e3/evidence && cd ~/e2e3
```

## 0. Cost and the 12-hour clock

- **Compute: about $0.25 to $0.50** for a 4 to 6 hour run: one ALB (about $0.0225/h plus a few
  LCUs), one or two Fargate tasks at 0.25 vCPU and 0.5 GB (about $0.012/h each), public IPv4
  addresses at $0.005/h (two for the ALB, one per task), and the StackSet's KMS key (prorated, a
  few cents). Lambda, CloudWatch and Route 53 queries are negligible. Public ACM certificates are
  free.
- **Hosted zones: free if deleted within 12 hours of creation**, otherwise $0.50 each for the
  month. The run creates three: the test root zone (step 1), the app zone and the env zone
  (Copilot). Write down the time step 1 runs; **start cleanup by T+10 h whatever the state of the
  run**. A zone can only be deleted once it holds nothing but its apex NS and SOA records (step 9).
- No NAT gateway: every workload uses public placement.

## 1. Prerequisites

1. Tools: `dig`, `curl`, `jq`, `openssl`, Terraform with the plugin cache, ecsodus from the branch
   that has the custom-domain fixes (`uv run ecsodus --version`).
2. Record the account's baseline (zones, certificates, load balancers):
   ```sh
   aws route53 list-hosted-zones > evidence/baseline-zones.json
   aws acm list-certificates > evidence/baseline-certs.json
   aws elbv2 describe-load-balancers > evidence/baseline-lbs.json
   ```
3. Create the test root zone (**T = now**) and record its ID and name servers:
   ```sh
   date -u +%FT%TZ > evidence/T0.txt
   aws route53 create-hosted-zone --name "$ROOT" --caller-reference "e2e3-$(date +%s)" \
     --hosted-zone-config Comment="ecsodus issue 6 test root, delete by T+12h" \
     > evidence/root-zone.json
   export ROOT_ZONE=$(jq -r '.HostedZone.Id | split("/")[-1]' evidence/root-zone.json)
   jq -r '.DelegationSet.NameServers[]' evidence/root-zone.json
   ```
4. **Maintainer, at the registrar or parent DNS of `<DOMAIN>`:** add an NS record for
   `ecsodus-test` with those four name servers (TTL 300).
5. Wait until public resolvers follow the delegation. ACM validation fails without it, and
   `copilot env deploy` then times out in `HTTPSCert`:
   ```sh
   dig +short NS "$ROOT" @1.1.1.1    # must print the four awsdns name servers
   dig +short NS "$ROOT" @8.8.8.8
   ```

## 2. Deploy the Copilot app

`copilot app init --domain` looks up the hosted zone for the domain in the account. A zone for a
delegated subdomain is expected to work as the app's root domain (**verify on the first command**;
if Copilot refuses it, stop and clean up step 1).

```sh
mkdir -p app && cd app
$COPILOT app init "$APP" --domain "$ROOT"
$COPILOT env init --name "$ENV" --profile "$AWS_PROFILE" --default-config
$COPILOT env deploy --name "$ENV"
$COPILOT svc init --name web --svc-type "Load Balanced Web Service" \
  --image public.ecr.aws/nginx/nginx:stable-alpine --port 80
```

Replace `copilot/web/manifest.yml` with this. Three aliases put a validation CNAME and an A record
into each of the three zones: env zone (`www.test...`), app zone (`web.ecsodus-e2e3...`) and the
root zone (`web.ecsodus-test...`, which ecsodus reports as an external reference).

```yaml
name: web
type: Load Balanced Web Service
image:
  location: public.ecr.aws/nginx/nginx:stable-alpine
  port: 80
http:
  path: '/'
  alias:
    - www.test.ecsodus-e2e3.ecsodus-test.<DOMAIN>
    - web.ecsodus-e2e3.ecsodus-test.<DOMAIN>
    - web.ecsodus-test.<DOMAIN>
cpu: 256
memory: 512
count: 1
exec: false
network:
  vpc:
    placement: public
```

Optional second service, to exercise the CloudFormation-owned `LoadBalancerDNSAlias` record in the
env zone (gap-analysis fix 2; about $0.012/h more). Per `copilot-stacks.md` §4.1 an HTTPS service
without an alias gets `plain.test.<app>.<root>`; **check the deployed template has
`LoadBalancerDNSAlias`** before relying on it.

```sh
$COPILOT svc init --name plain --svc-type "Load Balanced Web Service" \
  --image public.ecr.aws/nginx/nginx:stable-alpine --port 80
```

```yaml
# copilot/plain/manifest.yml
name: plain
type: Load Balanced Web Service
image:
  location: public.ecr.aws/nginx/nginx:stable-alpine
  port: 80
http:
  path: 'plain'
cpu: 256
memory: 512
count: 1
exec: false
network:
  vpc:
    placement: public
```

```sh
$COPILOT svc deploy --name web --env "$ENV"
$COPILOT svc deploy --name plain --env "$ENV"   # optional
```

Deploying `web` changes the env's `Aliases`, so `HTTPSCert` requests a new certificate (with the
aliases) and Copilot's Delete handler removes the first one, keeping the validation CNAME both
share. **Do not change any manifest after this point**: ecsodus migrates what is deployed.

## 3. Record identifiers

```sh
ENV_STACK="$APP-$ENV"
res() { aws cloudformation describe-stack-resource --stack-name "$1" --logical-resource-id "$2" \
  --query StackResourceDetail.PhysicalResourceId --output text; }
export APP_ZONE=$(res "$APP-infrastructure-roles" AppHostedZone)
export ENV_ZONE=$(res "$ENV_STACK" EnvironmentHostedZone)
export CERT_ARN=$(res "$ENV_STACK" HTTPSCert)
for fn in CertificateValidationFunction DNSDelegationFunction CustomDomainFunction; do
  echo "$fn $(res "$ENV_STACK" $fn)"; done > evidence/dns-lambdas.txt
for svc in web plain; do for fn in EnvControllerFunction RulePriorityFunction; do
  echo "$svc/$fn $(res "$ENV_STACK-$svc" $fn 2>/dev/null)"; done; done > evidence/svc-lambdas.txt
env | grep -E '^(ROOT_ZONE|APP_ZONE|ENV_ZONE|CERT_ARN)=' > evidence/ids.env
```

## 4. Measurements (take them twice: before step 7 and after step 8)

Save each set under `evidence/before/` and `evidence/after/`. The run passes only if every
`diff` in step 8 is empty and every check holds.

```sh
measure() {  # usage: measure before|after
  d=evidence/$1; mkdir -p $d
  # M1. Certificates: status, in-use, SANs and validation records; and how many carry the app tag.
  aws acm describe-certificate --certificate-arn "$CERT_ARN" \
    --query 'Certificate.{Status:Status,InUseBy:InUseBy,SANs:SubjectAlternativeNames,
      DVO:DomainValidationOptions[].ResourceRecord,Renewal:RenewalEligibility}' > $d/cert.json
  for a in $(aws acm list-certificates --query 'CertificateSummaryList[].CertificateArn' --output text); do
    aws acm list-tags-for-certificate --certificate-arn "$a" \
      --query "Tags[?Key=='copilot-application'&&Value=='$APP'] | [0].Value" --output text \
      | grep -q "$APP" && echo "$a"; done | sort > $d/tagged-certs.txt
  # M2. Every record in the three zones (root, app, env).
  for z in ROOT_ZONE APP_ZONE ENV_ZONE; do
    aws route53 list-resource-record-sets --hosted-zone-id "${!z}" \
      | jq -S '.ResourceRecordSets | sort_by(.Name, .Type)' > $d/records-$z.json; done
  # M3. Handler invocations since the app was created (Sum over 1-minute periods).
  start=$(cat evidence/T0.txt); now=$(date -u +%FT%TZ)
  cat evidence/dns-lambdas.txt evidence/svc-lambdas.txt | while read name fn; do
    [ -n "$fn" ] && [ "$fn" != None ] || continue
    n=$(aws cloudwatch get-metric-statistics --namespace AWS/Lambda --metric-name Invocations \
      --dimensions Name=FunctionName,Value="$fn" --start-time "$start" --end-time "$now" \
      --period 60 --statistics Sum --query 'sum(Datapoints[].Sum)' --output text)
    echo "$name $n"; done > $d/invocations.txt
  # M4. Public DNS through the whole delegation chain.
  for n in "$ROOT" "ecsodus-e2e3.$ROOT" "test.ecsodus-e2e3.$ROOT"; do
    echo "NS $n: $(dig +short NS $n @1.1.1.1 | sort | tr '\n' ' ')"; done > $d/dig.txt
  jq -r '.DVO[] | .Name' $d/cert.json | sort -u | while read v; do
    echo "CNAME $v: $(dig +short CNAME $v @1.1.1.1)"; done >> $d/dig.txt
  # M5. HTTPS on every alias (and the plain service's default name, if deployed).
  for h in "www.test.ecsodus-e2e3.$ROOT" "web.ecsodus-e2e3.$ROOT" "web.$ROOT"; do
    echo "$h $(curl -sS -o /dev/null -w '%{http_code} verify=%{ssl_verify_result}' https://$h/)"
  done > $d/https.txt
  echo "plain.test.ecsodus-e2e3.$ROOT $(curl -sS -o /dev/null -w '%{http_code}' \
    https://plain.test.ecsodus-e2e3.$ROOT/plain 2>&1)" >> $d/https.txt
  echo | openssl s_client -connect "web.$ROOT:443" -servername "web.$ROOT" 2>/dev/null \
    | openssl x509 -noout -serial -enddate > $d/served-cert.txt
}
measure before
```

Expected before teardown: `cert.json` Status `ISSUED`, `InUseBy` = the env ALB, `Renewal`
`ELIGIBLE`; `tagged-certs.txt` has exactly one ARN (R4: if two, the old certificate survived
Copilot's own Delete; note it, both get imported); `https.txt` is `200 verify=0` for the three
aliases (the plain service returns nginx's 404 for `/plain`, which still proves routing and TLS).

## 5. ecsodus: inventory, report, generate

Follow the generated `RUNBOOK.md` exactly as in the 2026-09-30 run. Custom-domain gates on top:

```sh
cd ~/e2e3
uv run ecsodus inventory --app "$APP" --region "$AWS_REGION" -o inventory.json
uv run ecsodus generate inventory.json --out infra --patch-bucket <retain-patch-bucket>
```

G1. `infra/REPORT.md`: every stack ready, and

- imports include: `aws_acm_certificate` (with `tags` for `copilot-application` and
  `copilot-environment`), two `aws_route53_zone` (app, env), and `aws_route53_record` for:
  `AppDomainDelegationRecordSet` (`<ROOT_ZONE>_ecsodus-e2e3.<root>_NS`), the env NS delegation in
  the app zone (out of band), validation CNAMEs (env zone: one shared by the env name and its
  wildcard, one for `www.test...`; app zone: one for `web.ecsodus-e2e3...`), the A aliases
  `www.test...` (env zone) and `web.ecsodus-e2e3...` (app zone), and `plain.test...` exactly once
  (from the `plain` stack, not as `out-of-band:`);
- "External references" lists exactly two `out-of-band:` rows, both in the root zone: the
  validation CNAME for `web.<root>` and the A record `web.<root>`;
- "Manual cleanup" lists the three DNS Lambdas, and the handles `HTTPSCert`, `DelegateDNSAction`
  and `CustomDomainAction` only under "Custom-resource handles", without physical IDs.

Compare G1 with M2: every non-apex record in the app and env zones must be an import, and every
non-apex record Copilot added to the root zone must be either the imported NS record or an
external reference.

## 6. Dry plan, protect, retain patches, import

As in `RUNBOOK.md` steps 1 to 4. **G2: the dry plan must be N/N pure imports.** Watch-list for
this run:

- the certificate (tags; `subject_alternative_names` without the domain name itself);
- `AppDomainDelegationRecordSet` NS values (R1: if the plan shows records changing from
  `ns-x.awsdns-y.org.` to `ns-x.awsdns-y.org`, Route 53 returns dotted values; stop, record it,
  and fix by reading the record live, gap-analysis D2);
- both zones (`comment`, live `tags`);
- out-of-band alias records (`alias.name` lower case, `evaluate_target_health = true`).

Every mismatch the gate refuses is a defect to fix offline and re-run from step 5, as in earlier
runs. `verify-retain` must pass for every stack before step 7.

## 7. Teardown

As in `RUNBOOK.md` step 5: workload stacks, env, StackSet instance (`--retain-stacks`), StackSet,
app stack, each after `verify-retain`. Then wait at least 5 minutes for Lambda metrics.

## 8. Verify

```sh
measure after
for f in cert.json tagged-certs.txt records-ROOT_ZONE.json records-APP_ZONE.json \
  records-ENV_ZONE.json invocations.txt dig.txt https.txt served-cert.txt; do
  diff -u evidence/before/$f evidence/after/$f && echo "same: $f"; done
cd infra && terraform plan -out tf-final.plan && terraform show -json tf-final.plan > plan-final.json \
  && uv run ecsodus check plan-final.json --manifest ecsodus-manifest.json --phase steady
```

Pass criteria:

- **Q4 answered:** every validation CNAME (env, app and root zones) is still present
  (`records-*.json` identical) and still resolves (`dig.txt`), and the certificate is `ISSUED`,
  in use and renewal-eligible.
- **No Delete handler ran:** `invocations.txt` identical. `CertificateValidationFunction`,
  `DNSDelegationFunction` and `CustomDomainFunction` keep their pre-teardown counts (expected
  Create plus the alias-driven Update and old-certificate Delete, all before step 7), and
  `EnvControllerFunction`/`RulePriorityFunction` keep theirs.
- NS delegations intact at every level (`dig.txt`), HTTPS `200 verify=0` on all three aliases, the
  same certificate served (`served-cert.txt`).
- Steady plan: all imported addresses no-op.

## 9. Cleanup checklist

Do all of it even if the run failed part-way. Hosted zones must be gone before T+12 h.

1. **Terraform-owned resources.** As in the 2026-10-07 run: empty the artifact bucket, lift
   `prevent_destroy` (certificate, zones, stateful resources), then
   `terraform plan -destroy -out destroy.plan`, review, apply. Expect a second pass: the listener
   holds the certificate ARN as a literal (no dependency edge), so ACM can refuse the delete while
   the listener exists, and a zone cannot be deleted while it still holds records.
2. **Records Terraform does not own** (the two external references in the root zone, and anything
   left in the app or env zone after a failed run). For each zone that still exists:
   ```sh
   purge_zone() {  # deletes every record except the apex NS and SOA, then the zone
     z=$1; apex=$(aws route53 get-hosted-zone --id "$z" --query HostedZone.Name --output text)
     aws route53 list-resource-record-sets --hosted-zone-id "$z" \
       | jq --arg apex "$apex" '{Changes: [.ResourceRecordSets[]
           | select(.Name != $apex or (.Type != "NS" and .Type != "SOA"))
           | {Action: "DELETE", ResourceRecordSet: .}]}' > /tmp/purge-$z.json
     [ "$(jq '.Changes | length' /tmp/purge-$z.json)" = 0 ] || \
       aws route53 change-resource-record-sets --hosted-zone-id "$z" --change-batch file:///tmp/purge-$z.json
     aws route53 delete-hosted-zone --id "$z"
   }
   purge_zone "$ENV_ZONE"; purge_zone "$APP_ZONE"; purge_zone "$ROOT_ZONE"
   ```
   Review `/tmp/purge-*.json` before each change batch.
3. **Certificates.** `aws acm list-certificates`: delete every certificate tagged
   `copilot-application=ecsodus-e2e3` that is left (`aws acm delete-certificate`), including a
   stale one from R4.
4. **Copilot leftovers** (listed in `RUNBOOK.md` step 6): the DNS Lambdas
   (`evidence/dns-lambdas.txt`), each service's `EnvControllerFunction` and
   `RulePriorityFunction`, their `/aws/lambda/...` log groups, Copilot's SSM parameters under
   `/copilot/applications/ecsodus-e2e3`, the retain-patch bucket, inactive task definitions, and
   the StackSet's KMS key (schedule deletion). Delete nothing by a `Custom::*` handle's physical ID.
5. **Maintainer, at the registrar or parent DNS:** remove the `ecsodus-test` NS record.
6. **Baseline.** `list-hosted-zones`, `list-certificates` and `describe-load-balancers` match
   `evidence/baseline-*.json`; no VPC other than the default one; record the time the last zone
   was deleted (must be before T+12 h).

## 10. Write-up

Add `docs/e2e/<date>-aws-e2e-custom-domain.md` in the style of the earlier runs: the app, the
result table, the answer to PLAN §6 question 4 with the invocation counts, defects found, and the
cleanup statement. Then drop custom domains from `VERIFIED_SCOPE` in `emit/runbook.py`.
