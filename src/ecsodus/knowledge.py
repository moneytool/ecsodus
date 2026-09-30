"""Machine-usable facts about AWS Copilot CLI stacks and custom resources.

Plain data only (no logic). Derived from reading the archived AWS Copilot CLI source
(https://github.com/aws/copilot-cli, Apache-2.0) at commit ``a0dbe689`` ("fix __inner override").
The human-readable versions, with file citations, are ``docs/knowledge/copilot-custom-resources.md``
and ``docs/knowledge/copilot-stacks.md``. Values that could not be confirmed in that source carry
``"unconfirmed": True`` or an ``(UNCONFIRMED)`` note.

Stack-kind strings match ``ecsodus.model`` (``"app"``, ``"stackset-instance"``, ``"env"``,
``"workload"``, ``"addons"``, ``"env-addons"``).

ecsodus fate rule (PLAN.md section 2.2): every ``Custom::*`` handle, and its Lambda, role and log
group, is ``manual-cleanup`` and is ALWAYS retain-patched. The out-of-band objects a handler created
are ``import``.
"""

from __future__ import annotations

from typing import Any, Final

COPILOT_SOURCE_COMMIT: Final = "a0dbe689"

# ---------------------------------------------------------------------------------------------
# Custom resources, one entry per source file in cf-custom-resources/lib/.
# "destructive" is True when the Delete handler removes or changes something that outlives the
# handle: a certificate, DNS records, bucket contents, or resources in another stack.
# "out_of_band" lists what the handler creates outside CloudFormation. It is empty when nothing is
# created. "distinguish_by" gives properties/handler strings that separate files which share a
# Custom:: type name.
# ---------------------------------------------------------------------------------------------

_ALB_RULE_PRIORITY: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/alb-rule-priority-generator.js",
    "types": ("Custom::RulePriorityFunction",),
    "function_logical_ids": ("RulePriorityFunction",),
    "handler": "index.nextAvailableRulePriorityHandler",
    "stack_kinds": ("workload",),
    "workload_types": ("Load Balanced Web Service", "Backend Service"),
    "logical_ids": (
        "HTTPRulePriorityAction",
        "HTTPSRulePriorityAction",
        "HTTPRuleWithDomainPriorityAction",
        "HTTPRedirectRulePriorityAction",
    ),
    "outputs": ("Priority", "Priority{i}"),
    "delete_behaviour": "no-op",
    "destructive": False,
    "out_of_band": (),
    "terraform": "literal priority on aws_lb_listener_rule (read from live DescribeRules)",
    "v01_scope": "in",
}

_BACKLOG_PER_TASK: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/backlog-per-task-calculator.js",
    "types": (),  # not a custom resource: Lambda invoked by an Events rule every minute
    "function_logical_ids": ("BacklogPerTaskCalculatorFunction",),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Worker Service",),
    "logical_ids": (),
    "outputs": (),
    "delete_behaviour": "none (not a custom resource)",
    "destructive": False,
    "out_of_band": ("CloudWatch EMF metric BacklogPerTask (dimension QueueName)",),
    "terraform": "aws_lambda_function + aws_cloudwatch_event_rule/_target + aws_lambda_permission",
    "v01_scope": "blocked",
}

_BUCKET_CLEANER: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/bucket-cleaner.js",
    "types": ("Custom::BucketCleanerFunction",),
    "function_logical_ids": ("BucketCleanerFunction",),
    "handler": "index.handler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("ELBAccessLogsBucketCleanerAction",),
    "outputs": (),
    "delete_behaviour": (
        "deletes every object version and delete marker in BucketName (ELBAccessLogsBucket)"
    ),
    "destructive": True,
    "out_of_band": (),
    "terraform": "none; import aws_s3_bucket and never set force_destroy",
    "v01_scope": "in",
}

_CERT_REPLICATOR: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/cert-replicator.js",
    "types": ("Custom::CertificateReplicatorFunction",),
    "function_logical_ids": ("CertificateReplicatorFunction",),
    "handler": "index.certificateReplicateHandler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("CertificateReplicator",),
    "outputs": ("Arn",),
    "delete_behaviour": (
        "if physical id is an ARN: wait up to 10x30s for InUseBy empty (else FAILED), "
        "then DeleteCertificate in us-east-1"
    ),
    "destructive": True,
    "out_of_band": (
        "ACM certificate in us-east-1 (tags copilot-application, copilot-environment)",
    ),
    "terraform": "aws_acm_certificate with a us-east-1 provider alias",
    "v01_scope": "blocked",  # CloudFront CDN
}

_CUSTOM_DOMAIN_ENV: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/custom-domain.js",
    "types": ("Custom::CustomDomainFunction",),
    "function_logical_ids": ("CustomDomainFunction",),
    "handler": "index.handler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("CustomDomainAction",),
    "outputs": (),
    "distinguish_by": ("PublicAccessHostedZone", "AppDNSRole", "Aliases is a JSON string"),
    "delete_behaviour": (
        "DELETE the A-alias record for every alias in Aliases (env/app/root zone); "
        "not-found ignored"
    ),
    "destructive": True,
    "out_of_band": (
        "Route 53 A-alias record per alias in the env zone (env account) or the app/root zone "
        "(app account via AppDNSDelegationRole)",
    ),
    "terraform": "aws_route53_record (type A, alias block)",
    "v01_scope": "in",
}

_CUSTOM_DOMAIN_APP_RUNNER: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/custom-domain-app-runner.js",
    "types": ("Custom::CustomDomainFunction",),
    "function_logical_ids": ("CustomDomainFunction",),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Request-Driven Web Service",),
    "logical_ids": ("CustomDomainAction",),
    "outputs": (),
    "distinguish_by": ("ServiceARN", "CustomDomain", "AppDNSName"),
    "delete_behaviour": (
        "DisassociateCustomDomain, DELETE the domain CNAME and every certificate validation "
        "CNAME, wait until disassociated"
    ),
    "destructive": True,
    "out_of_band": (
        "App Runner custom domain association",
        "Route 53 CNAME <domain> -> App Runner DNSTarget (app zone)",
        "Route 53 certificate validation CNAMEs (app zone)",
    ),
    "terraform": "aws_apprunner_custom_domain_association + aws_route53_record (CNAME)",
    "v01_scope": "blocked",
}

_DESIRED_COUNT: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/desired-count-delegation.js",
    "types": ("Custom::DynamicDesiredCountFunction",),
    "function_logical_ids": ("DynamicDesiredCountFunction",),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Load Balanced Web Service", "Backend Service", "Worker Service"),
    "logical_ids": ("DynamicDesiredCountAction",),
    "outputs": ("DesiredCount",),
    "delete_behaviour": "no-op",
    "destructive": False,
    "out_of_band": (),
    "terraform": "aws_ecs_service.desired_count with lifecycle ignore_changes",
    "v01_scope": "in",
}

_DNS_CERT_VALIDATOR: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/dns-cert-validator.js",
    "types": ("Custom::CertificateValidationFunction",),
    "function_logical_ids": ("CertificateValidationFunction",),
    "handler": "index.certificateRequestHandler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("HTTPSCert",),
    "outputs": ("Arn",),
    "distinguish_by": ("handler index.certificateRequestHandler", "Region", "Aliases JSON string"),
    "delete_behaviour": (
        "if physical id is an ARN: wait up to 10x30s for InUseBy empty (else FAILED); DELETE "
        "validation CNAMEs not used by another cert with the same DomainName; DeleteCertificate"
    ),
    "destructive": True,
    "out_of_band": (
        "ACM certificate <env>.<app>.<domain> + *.<env>.<app>.<domain> + aliases "
        "(tags copilot-application, copilot-environment)",
        "Route 53 validation CNAMEs in the env zone and/or the app/root zone (app account)",
    ),
    "terraform": (
        "aws_acm_certificate + aws_route53_record (validation) (+ aws_acm_certificate_validation)"
    ),
    "v01_scope": "in",
}

_DNS_DELEGATION: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/dns-delegation.js",
    "types": ("Custom::DNSDelegationFunction",),
    "function_logical_ids": ("DNSDelegationFunction",),
    "handler": "index.domainDelegationHandler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("DelegateDNSAction",),
    "outputs": (),
    "delete_behaviour": (
        "DELETE the NS record <env>.<app>.<domain> from the app hosted zone (via RootDNSRole) "
        "if it exactly matches"
    ),
    "destructive": True,
    "out_of_band": (
        "Route 53 NS record <env>.<app>.<domain> in the app hosted zone <app>.<domain> "
        "(app account)",
    ),
    "terraform": "aws_route53_record (type NS) in the app zone, app-account provider",
    "v01_scope": "in",
}

_ENV_CONTROLLER: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/env-controller.js",
    "types": ("Custom::EnvControllerFunction",),
    "function_logical_ids": ("EnvControllerFunction",),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": (
        "Load Balanced Web Service",
        "Backend Service",
        "Worker Service",
        "Request-Driven Web Service",
        "Scheduled Job",
    ),
    "logical_ids": ("EnvControllerAction",),
    "outputs": ("<every env stack output except EnabledFeatures, LastForceDeployID>",),
    "delete_behaviour": (
        "remove the workload from every *Workloads parameter and from Aliases of stack "
        "<app>-<env>, then UpdateStack(UsePreviousTemplate=true); if it was the last user of a "
        "feature, CloudFormation deletes that feature's env resources (ALB, NAT, EFS FileSystem, "
        "internal ALB, App Runner endpoint, CustomDomainAction) and reissues HTTPSCert on an "
        "Aliases change"
    ),
    "destructive": True,  # indirectly, through the env stack update
    "out_of_band": (),  # changes another stack's parameters; creates nothing outside CFN
    "terraform": "none; env resources become unconditional Terraform resources",
    "v01_scope": "in",
}

_TRIGGER_STATE_MACHINE: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/trigger-state-machine.js",
    "types": ("Custom::TriggerStateMachine",),
    "function_logical_ids": ("TriggerStateMachineFunction",),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Static Site",),
    "logical_ids": ("TriggerStateMachineAction",),
    "outputs": (),
    "delete_behaviour": "no-op",
    "destructive": False,
    "out_of_band": ("S3 objects copied into the static-site Bucket by CopyAssetsStateMachine",),
    "terraform": "none (asset upload becomes a CI step)",
    "v01_scope": "blocked",
}

_UNIQUE_JSON_VALUES: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/unique-json-values.js",
    "types": ("Custom::UniqueJSONValuesFunction",),
    "function_logical_ids": ("UniqueJSONValuesFunction",),
    "handler": "index.handler",
    "stack_kinds": ("env",),
    "workload_types": (),
    "logical_ids": ("UniqueAliasesAction",),
    "outputs": ("UniqueValues",),
    "delete_behaviour": "no-op",
    "destructive": False,
    "out_of_band": (),
    "terraform": "literal aliases list on aws_cloudfront_distribution",
    "v01_scope": "blocked",  # CloudFront CDN
}

_WKLD_CERT_VALIDATOR: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/wkld-cert-validator.js",
    "types": ("Custom::NLBCertValidatorFunction", "Custom::CertificateValidationFunction"),
    "function_logical_ids": ("NLBCertValidatorFunction", "CertificateValidationFunction"),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Load Balanced Web Service", "Static Site"),
    "logical_ids": ("NLBCertValidatorAction", "CertificateValidatorAction"),
    "outputs": (),
    "distinguish_by": (
        "ServiceName",
        "LoadBalancerDNS (NLB)",
        "IsCloudFrontCertificate (static site)",
    ),
    "delete_behaviour": (
        "DELETE this service's validation CNAMEs not shared with its other certs or other "
        "services; "
        "wait up to 12x30s for InUseBy empty (else FAILED); DeleteCertificate"
    ),
    "destructive": True,
    "out_of_band": (
        "ACM certificate <svc>-nlb.<env>.<app>.<domain> (NLB) or <svc>.<env>.<app>.<domain> in "
        "us-east-1 (static site), tags copilot-application/-environment/-service",
        "Route 53 validation CNAMEs",
    ),
    "terraform": "aws_acm_certificate + aws_route53_record (validation)",
    "v01_scope": "blocked",  # NLB, Static Site
}

_WKLD_CUSTOM_DOMAIN: Final[dict[str, Any]] = {
    "file": "cf-custom-resources/lib/wkld-custom-domain.js",
    "types": ("Custom::NLBCustomDomainFunction", "Custom::CustomDomainFunction"),
    "function_logical_ids": ("NLBCustomDomainFunction", "CustomDomainFunction"),
    "handler": "index.handler",
    "stack_kinds": ("workload",),
    "workload_types": ("Load Balanced Web Service", "Static Site"),
    "logical_ids": ("NLBCustomDomainAction", "CustomDomainAction"),
    "outputs": (),
    "distinguish_by": ("PublicAccessHostedZoneID", "ServiceName", "RootDNSRole"),
    "delete_behaviour": (
        "DELETE the A-alias record for every alias pointing at the current target; not-found and "
        "value-mismatch ignored"
    ),
    "destructive": True,
    "out_of_band": ("Route 53 A-alias records for the aliases (to the NLB or CloudFront)",),
    "terraform": "aws_route53_record (type A, alias block)",
    "v01_scope": "blocked",  # NLB, Static Site
}

#: Source file name (basename) -> facts. Covers all 14 files in cf-custom-resources/lib/.
CUSTOM_RESOURCE_FILES: Final[dict[str, dict[str, Any]]] = {
    "alb-rule-priority-generator.js": _ALB_RULE_PRIORITY,
    "backlog-per-task-calculator.js": _BACKLOG_PER_TASK,
    "bucket-cleaner.js": _BUCKET_CLEANER,
    "cert-replicator.js": _CERT_REPLICATOR,
    "custom-domain-app-runner.js": _CUSTOM_DOMAIN_APP_RUNNER,
    "custom-domain.js": _CUSTOM_DOMAIN_ENV,
    "desired-count-delegation.js": _DESIRED_COUNT,
    "dns-cert-validator.js": _DNS_CERT_VALIDATOR,
    "dns-delegation.js": _DNS_DELEGATION,
    "env-controller.js": _ENV_CONTROLLER,
    "trigger-state-machine.js": _TRIGGER_STATE_MACHINE,
    "unique-json-values.js": _UNIQUE_JSON_VALUES,
    "wkld-cert-validator.js": _WKLD_CERT_VALIDATOR,
    "wkld-custom-domain.js": _WKLD_CUSTOM_DOMAIN,
}

#: Custom:: type name -> the file entries that can back it. A type name is NOT unique:
#: Custom::CustomDomainFunction has three backing files and Custom::CertificateValidationFunction
#: has two. Pick the entry by stack kind / workload type (see each entry's "distinguish_by").
#: "destructive" at this level is True if any backing file's Delete is destructive.
CUSTOM_RESOURCES: Final[dict[str, dict[str, Any]]] = {
    "Custom::RulePriorityFunction": {"destructive": False, "variants": (_ALB_RULE_PRIORITY,)},
    "Custom::BucketCleanerFunction": {"destructive": True, "variants": (_BUCKET_CLEANER,)},
    "Custom::CertificateReplicatorFunction": {"destructive": True, "variants": (_CERT_REPLICATOR,)},
    "Custom::CustomDomainFunction": {
        "destructive": True,
        "variants": (_CUSTOM_DOMAIN_ENV, _CUSTOM_DOMAIN_APP_RUNNER, _WKLD_CUSTOM_DOMAIN),
    },
    "Custom::DynamicDesiredCountFunction": {"destructive": False, "variants": (_DESIRED_COUNT,)},
    "Custom::CertificateValidationFunction": {
        "destructive": True,
        "variants": (_DNS_CERT_VALIDATOR, _WKLD_CERT_VALIDATOR),
    },
    "Custom::DNSDelegationFunction": {"destructive": True, "variants": (_DNS_DELEGATION,)},
    "Custom::EnvControllerFunction": {"destructive": True, "variants": (_ENV_CONTROLLER,)},
    "Custom::TriggerStateMachine": {"destructive": False, "variants": (_TRIGGER_STATE_MACHINE,)},
    "Custom::UniqueJSONValuesFunction": {"destructive": False, "variants": (_UNIQUE_JSON_VALUES,)},
    "Custom::NLBCertValidatorFunction": {"destructive": True, "variants": (_WKLD_CERT_VALIDATOR,)},
    "Custom::NLBCustomDomainFunction": {"destructive": True, "variants": (_WKLD_CUSTOM_DOMAIN,)},
}

#: (stack kind, workload type or None for env) -> Lambda logical ID -> source file.
#: From internal/pkg/deploy/upload/customresource/customresource.go.
CUSTOM_RESOURCE_FUNCTIONS: Final[dict[tuple[str, str | None], dict[str, str]]] = {
    ("env", None): {
        "CertificateValidationFunction": "dns-cert-validator.js",
        "CustomDomainFunction": "custom-domain.js",
        "DNSDelegationFunction": "dns-delegation.js",
        "CertificateReplicatorFunction": "cert-replicator.js",
        "BucketCleanerFunction": "bucket-cleaner.js",
        "UniqueJSONValuesFunction": "unique-json-values.js",
    },
    ("workload", "Load Balanced Web Service"): {
        "DynamicDesiredCountFunction": "desired-count-delegation.js",
        "EnvControllerFunction": "env-controller.js",
        "RulePriorityFunction": "alb-rule-priority-generator.js",
        "NLBCustomDomainFunction": "wkld-custom-domain.js",
        "NLBCertValidatorFunction": "wkld-cert-validator.js",
    },
    ("workload", "Backend Service"): {
        "DynamicDesiredCountFunction": "desired-count-delegation.js",
        "RulePriorityFunction": "alb-rule-priority-generator.js",
        "EnvControllerFunction": "env-controller.js",
    },
    ("workload", "Worker Service"): {
        "DynamicDesiredCountFunction": "desired-count-delegation.js",
        "BacklogPerTaskCalculatorFunction": "backlog-per-task-calculator.js",
        "EnvControllerFunction": "env-controller.js",
    },
    ("workload", "Request-Driven Web Service"): {
        "EnvControllerFunction": "env-controller.js",
        "CustomDomainFunction": "custom-domain-app-runner.js",
    },
    ("workload", "Static Site"): {
        "TriggerStateMachineFunction": "trigger-state-machine.js",
        "CertificateValidationFunction": "wkld-cert-validator.js",
        "CustomDomainFunction": "wkld-custom-domain.js",
    },
    ("workload", "Scheduled Job"): {
        "EnvControllerFunction": "env-controller.js",
    },
}

#: Runtime of every custom-resource Lambda in the templates.
CUSTOM_RESOURCE_RUNTIME: Final = "nodejs20.x"

# ---------------------------------------------------------------------------------------------
# Environment stack (internal/pkg/template/templates/environment/cf.yml + partials)
# ---------------------------------------------------------------------------------------------

#: The env parameters the env-controller mutates (template.AvailableEnvFeatures()).
ENV_CONTROLLER_PARAMETERS: Final = (
    "ALBWorkloads",
    "EFSWorkloads",
    "NATWorkloads",
    "InternalALBWorkloads",
    "Aliases",
    "AppRunnerPrivateWorkloads",
)

#: Env condition name -> (parameters it reads, the expression as written in cf.yml).
ENV_CONDITIONS: Final[dict[str, tuple[tuple[str, ...], str]]] = {
    "CreateALB": (("ALBWorkloads",), '!Not [!Equals [ !Ref ALBWorkloads, "" ]]'),
    "CreateInternalALB": (
        ("InternalALBWorkloads",),
        '!Not [!Equals [ !Ref InternalALBWorkloads, "" ]]',
    ),
    "DelegateDNS": (("AppDNSName",), '!Not [!Equals [ !Ref AppDNSName, "" ]]'),
    "ExportHTTPSListener": (
        ("ALBWorkloads", "CreateHTTPSListener"),
        "!And [!Condition CreateALB, !Equals [ !Ref CreateHTTPSListener, true ]]",
    ),
    "ExportInternalHTTPSListener": (
        ("InternalALBWorkloads", "CreateInternalHTTPSListener"),
        "!And [!Condition CreateInternalALB, !Equals [ !Ref CreateInternalHTTPSListener, true ]]",
    ),
    "CreateEFS": (("EFSWorkloads",), '!Not [!Equals [ !Ref EFSWorkloads, ""]]'),
    "CreateNATGateways": (("NATWorkloads",), '!Not [!Equals [ !Ref NATWorkloads, ""]]'),
    "CreateAppRunnerVPCEndpoint": (
        ("AppRunnerPrivateWorkloads",),
        '!Not [!Equals [ !Ref AppRunnerPrivateWorkloads, ""]]',
    ),
    "ManagedAliases": (
        ("AppDNSName", "Aliases", "ALBWorkloads"),
        '!And [!Condition DelegateDNS, !Not [!Equals [ !Ref Aliases, "" ]], !Condition CreateALB]',
    ),
}

#: Env resource logical ID -> {"condition", "parameters"}. "{n}" = one per subnet index (1-based)
#: or per extra imported certificate. Resources that are only render-gated (no CFN Condition) are
#: in ENV_RENDER_GATED_RESOURCES instead.
ENV_CONDITIONAL_RESOURCES: Final[dict[str, dict[str, Any]]] = {
    # CreateALB
    "PublicHTTPLoadBalancerSecurityGroup": {
        "condition": "CreateALB",
        "parameters": ("ALBWorkloads",),
    },
    "EnvironmentHTTPSecurityGroupIngressFromPublicALB": {
        "condition": "CreateALB",
        "parameters": ("ALBWorkloads",),
    },
    "PublicLoadBalancer": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "DefaultHTTPTargetGroup": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "HTTPListener": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "ELBAccessLogsBucketPolicy": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "UniqueJSONValuesFunctionRole": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "UniqueJSONValuesFunction": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "UniqueAliasesAction": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    "CloudFrontDistribution": {"condition": "CreateALB", "parameters": ("ALBWorkloads",)},
    # ExportHTTPSListener
    "PublicHTTPSLoadBalancerSecurityGroup": {
        "condition": "ExportHTTPSListener",
        "parameters": ("ALBWorkloads", "CreateHTTPSListener"),
    },
    "EnvironmentHTTPSSecurityGroupIngressFromPublicALB": {
        "condition": "ExportHTTPSListener",
        "parameters": ("ALBWorkloads", "CreateHTTPSListener"),
    },
    "HTTPSListener": {
        "condition": "ExportHTTPSListener",
        "parameters": ("ALBWorkloads", "CreateHTTPSListener"),
    },
    "HTTPSImportCertificate{n}": {
        "condition": "ExportHTTPSListener",
        "parameters": ("ALBWorkloads", "CreateHTTPSListener"),
    },
    # CreateInternalALB
    "InternalLoadBalancerSecurityGroup": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "EnvironmentSecurityGroupIngressFromInternalALB": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "InternalALBIngressFromEnvironmentSecurityGroup": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "InternalLoadBalancerSecurityGroupIngressFromHttp": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "InternalLoadBalancer": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "DefaultInternalHTTPTargetGroup": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "InternalHTTPListener": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    "InternalWorkloadsHostedZone": {
        "condition": "CreateInternalALB",
        "parameters": ("InternalALBWorkloads",),
    },
    # ExportInternalHTTPSListener
    "InternalLoadBalancerSecurityGroupIngressFromHttps": {
        "condition": "ExportInternalHTTPSListener",
        "parameters": ("InternalALBWorkloads", "CreateInternalHTTPSListener"),
    },
    "InternalHTTPSListener": {
        "condition": "ExportInternalHTTPSListener",
        "parameters": ("InternalALBWorkloads", "CreateInternalHTTPSListener"),
    },
    "InternalHTTPSImportCertificate{n}": {
        "condition": "ExportInternalHTTPSListener",
        "parameters": ("InternalALBWorkloads", "CreateInternalHTTPSListener"),
    },
    # CreateEFS
    "FileSystem": {"condition": "CreateEFS", "parameters": ("EFSWorkloads",)},
    "EFSSecurityGroup": {"condition": "CreateEFS", "parameters": ("EFSWorkloads",)},
    "EFSSecurityGroupIngressFromEnvironment": {
        "condition": "CreateEFS",
        "parameters": ("EFSWorkloads",),
    },
    "MountTarget{n}": {"condition": "CreateEFS", "parameters": ("EFSWorkloads",)},
    # CreateNATGateways (nat-gateways.yml, only when the VPC is not imported)
    "NatGateway{n}Attachment": {"condition": "CreateNATGateways", "parameters": ("NATWorkloads",)},
    "NatGateway{n}": {"condition": "CreateNATGateways", "parameters": ("NATWorkloads",)},
    "PrivateRouteTable{n}": {"condition": "CreateNATGateways", "parameters": ("NATWorkloads",)},
    "PrivateRoute{n}": {"condition": "CreateNATGateways", "parameters": ("NATWorkloads",)},
    "PrivateRouteTable{n}Association": {
        "condition": "CreateNATGateways",
        "parameters": ("NATWorkloads",),
    },
    # CreateAppRunnerVPCEndpoint (ar-vpc-connector.yml, only when the VPC is not imported)
    "AppRunnerVpcEndpointSecurityGroup": {
        "condition": "CreateAppRunnerVPCEndpoint",
        "parameters": ("AppRunnerPrivateWorkloads",),
    },
    "AppRunnerVpcEndpointSecurityGroupIngressFromEnvironment": {
        "condition": "CreateAppRunnerVPCEndpoint",
        "parameters": ("AppRunnerPrivateWorkloads",),
    },
    "AppRunnerVpcEndpoint": {
        "condition": "CreateAppRunnerVPCEndpoint",
        "parameters": ("AppRunnerPrivateWorkloads",),
    },
    # DelegateDNS (rendered only when not .PublicHTTPConfig.ImportedCertARNs)
    "CustomResourceRole": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "EnvironmentHostedZone": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "CertificateValidationFunction": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "DNSDelegationFunction": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "DelegateDNSAction": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "HTTPSCert": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "CertificateReplicatorFunction": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    "CertificateReplicator": {"condition": "DelegateDNS", "parameters": ("AppDNSName",)},
    # ManagedAliases
    "CustomDomainFunction": {
        "condition": "ManagedAliases",
        "parameters": ("AppDNSName", "Aliases", "ALBWorkloads"),
    },
    "CustomDomainAction": {
        "condition": "ManagedAliases",
        "parameters": ("AppDNSName", "Aliases", "ALBWorkloads"),
    },
}

#: Env resources with no CFN Condition, present only when a Go-template gate rendered them.
#: logical ID -> render gate as written in the template.
ENV_RENDER_GATED_RESOURCES: Final[dict[str, str]] = {
    "ELBAccessLogsBucket": ".PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket",
    "ELBAccessLogsBucketCleanerAction": ".PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket",
    "BucketCleanerFunction": ".PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket",
    "ELBAccessLogsBucketCleanerRole": ".PublicHTTPConfig.ELBAccessLogs.ShouldCreateBucket",
    "CloudFrontOriginAccessControl": ".CDNConfig.Static",
    "VPC": "not .VPCConfig.Imported",
    "PublicRouteTable": "not .VPCConfig.Imported",
    "DefaultPublicRoute": "not .VPCConfig.Imported",
    "InternetGateway": "not .VPCConfig.Imported",
    "InternetGatewayAttachment": "not .VPCConfig.Imported",
    "PublicSubnet{n}": "not .VPCConfig.Imported",
    "PrivateSubnet{n}": "not .VPCConfig.Imported",
    "PublicSubnet{n}RouteTableAssociation": "not .VPCConfig.Imported",
    "VpcFlowLogGroup": ".VPCConfig.FlowLogs",
    "FlowLog": ".VPCConfig.FlowLogs",
    "FlowLogRole": ".VPCConfig.FlowLogs",
    "AddonsStack": ".Addons",
}

#: Env resources whose DeletionPolicy is set in the Copilot source (all others have none).
ENV_SOURCE_DELETION_POLICIES: Final[dict[str, str]] = {
    "CloudformationExecutionRole": "Retain",
    "EnvironmentManagerRole": "Retain",
}

#: Workload template -> the env parameters its EnvControllerAction may request
#: (envControllerParameters in internal/pkg/template/workload.go).
ENV_CONTROLLER_PARAMETERS_BY_WORKLOAD: Final[dict[str, dict[str, str]]] = {
    "Load Balanced Web Service": {
        "ALBWorkloads": "ALB enabled and no imported ALB",
        "Aliases": "no imported ALB",
        "NATWorkloads": "network.vpc.placement is private (PrivateSubnets)",
        "EFSWorkloads": "Copilot-managed EFS volume (Storage.ManagedVolumeInfo)",
    },
    "Backend Service": {
        "InternalALBWorkloads": "ALB enabled and no imported ALB",
        "NATWorkloads": "network.vpc.placement is private (PrivateSubnets)",
        "EFSWorkloads": "Copilot-managed EFS volume (Storage.ManagedVolumeInfo)",
    },
    "Request-Driven Web Service": {
        "AppRunnerPrivateWorkloads": "private and no existing App Runner VPC endpoint",
    },
}

# ---------------------------------------------------------------------------------------------
# Addons: DeletionPolicy found in source, and the CloudFormation default that otherwise applies.
# Only the S3 bucket policy carries an explicit policy; no addon template sets UpdateReplacePolicy.
# ---------------------------------------------------------------------------------------------

ADDON_SOURCE_DELETION_POLICIES: Final[dict[str, str]] = {
    "AWS::S3::BucketPolicy": "Retain",  # {Name}BucketPolicy in addons/s3/cf.yml and s3/env/cf.yml
}

#: CloudFormation default DeletionPolicy behaviour when none is set
#: (AWS behaviour, not Copilot code).
CFN_DEFAULT_DELETE_BEHAVIOUR: Final[dict[str, dict[str, Any]]] = {
    "AWS::RDS::DBCluster": {
        "default": "Snapshot",
        "note": "final cluster snapshot taken, then deleted",
    },
    "AWS::RDS::DBInstance": {
        "default": "Delete if DBClusterIdentifier is set, else Snapshot",
        "note": "Copilot's Aurora writer instance sets DBClusterIdentifier, so Delete",
    },
    "AWS::SecretsManager::Secret": {
        "default": "Delete",
        "note": "deleted without a recovery window (PLAN.md section 1)",
        "unconfirmed": True,
    },
    "AWS::DynamoDB::Table": {
        "default": "Delete",
        "note": "table and items deleted; no PITR/protection in template",
    },
    "AWS::S3::Bucket": {
        "default": "Delete",
        "note": "fails (DELETE_FAILED) if the bucket is not empty",
    },
    "AWS::EFS::FileSystem": {"default": "Delete", "note": "file system and data deleted"},
    "AWS::KMS::Key": {
        "default": "Delete",
        "note": "scheduled for deletion, default 30-day window",
        "unconfirmed": True,
    },
    "AWS::ECR::Repository": {
        "default": "Delete",
        "note": "fails if images exist (EmptyOnDelete unset)",
        "unconfirmed": True,
    },
    "AWS::Route53::HostedZone": {"default": "Delete", "note": "fails if non-SOA/NS records remain"},
    "AWS::Logs::LogGroup": {"default": "Delete", "note": "log data deleted"},
}

# ---------------------------------------------------------------------------------------------
# Naming, tags and SSM metadata
# ---------------------------------------------------------------------------------------------

#: internal/pkg/deploy/deploy.go
TAG_APP: Final = "copilot-application"
TAG_ENV: Final = "copilot-environment"
TAG_SERVICE: Final = "copilot-service"
TAG_PIPELINE: Final = "copilot-pipeline"
TAG_TASK: Final = "copilot-task"

#: Stack kind -> tag keys Copilot puts on the stack (the app's AdditionalTags are merged in too).
STACK_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "app": (TAG_APP,),
    "stackset": (TAG_APP,),
    "env": (TAG_APP, TAG_ENV),
    "workload": (TAG_APP, TAG_ENV, TAG_SERVICE),
}

#: Stack-name patterns (internal/pkg/deploy/cloudformation/stack/name.go). Placeholders are
#: {app}, {env}, {svc}, {task}, {pipeline}.
STACK_NAME_PATTERNS: Final[dict[str, str]] = {
    "app": "{app}-infrastructure-roles",
    "stackset": "{app}-infrastructure",
    "env": "{app}-{env}",
    "workload": "{app}-{env}-{svc}",  # truncated to 128 characters
    "task": "task-{task}",
    "pipeline": "pipeline-{app}-{pipeline}",  # legacy pipelines: "{pipeline}"
}
WORKLOAD_STACK_NAME_MAX_LEN: Final = 128

#: StackSet instance stacks are named by CloudFormation, not Copilot (UNCONFIRMED pattern).
STACKSET_INSTANCE_NAME_PATTERN: Final = "StackSet-{app}-infrastructure-{uuid}"
STACKSET_INSTANCE_NAME_UNCONFIRMED: Final = True

#: Logical ID of the nested addons stack in env and workload templates
#: (template.AddonsStackLogicalID).
ADDONS_STACK_LOGICAL_ID: Final = "AddonsStack"

#: Other fixed names.
RESOURCE_NAME_PATTERNS: Final[dict[str, str]] = {
    "stackset_admin_role": "{app}-adminrole",
    "stackset_execution_role": "{app}-executionrole",
    "dns_delegation_role": "{app}-DNSDelegationRole",
    "env_cfn_execution_role": "{app}-{env}-CFNExecutionRole",
    "env_manager_role": "{app}-{env}-EnvManagerRole",
    "ecr_repository": "{app}/{svc}",
    "workload_log_group": "/copilot/{app}-{env}-{svc}",
    "app_hosted_zone": "{app}.{domain}",
    "env_hosted_zone": "{env}.{app}.{domain}",
    "internal_hosted_zone": "{env}.{app}.internal",
    "service_discovery_namespace": "{env}.{app}.local",  # legacy envs: "{app}.local"
    "artifact_key_export": "{app}-ArtifactKey",
    "env_export": "{app}-{env}-{output}",  # ${AWS::StackName}-<Name>
}

#: SSM metadata layout (internal/pkg/config/store.go). All are String parameters holding JSON.
SSM_SCHEMA_VERSION: Final = "1.0"
SSM_PATHS: Final[dict[str, str]] = {
    "applications_root": "/copilot/applications/",
    "application": "/copilot/applications/{app}",
    "environments_root": "/copilot/applications/{app}/environments/",
    "environment": "/copilot/applications/{app}/environments/{env}",
    "workloads_root": "/copilot/applications/{app}/components/",
    "workload": "/copilot/applications/{app}/components/{svc}",
    # copilot secret init (internal/pkg/cli/secret_init.go): SecureString, outside CloudFormation
    "secret": "/copilot/{app}/{env}/secrets/{name}",
}
SSM_JSON_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "application": (
        "name",
        "account",
        "permissionsBoundary",
        "domain",
        "domainHostedZoneID",
        "version",
        "tags",
    ),
    "environment": (
        "app",
        "name",
        "region",
        "accountID",
        "registryURL",
        "executionRoleARN",
        "managerRoleARN",
        "customConfig",
        "telemetry",  # deprecated, may be absent
    ),
    "workload": ("app", "name", "type"),
}
SSM_TAGS: Final[dict[str, tuple[str, ...]]] = {
    "application": (TAG_APP,),
    "environment": (TAG_APP, TAG_ENV),
    "workload": (TAG_APP, TAG_SERVICE),
    "secret": (TAG_APP, TAG_ENV),
}
