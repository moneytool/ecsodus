# Renders docs/assets/demo.gif. Run from a directory holding a Copilot inventory.json:
#   uv run python -c "from tests.golden import live_synth as a; a.build_app('aurora').save('inventory.json')"
#   vhs <repo>/docs/assets/demo.tape
Output demo.gif
Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 620
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms

Hide
Type "export PS1='$ ' && ecsodus --help >/dev/null && rm -rf infra REPORT.md && clear" Enter
Sleep 3s
Show

Type "# 1. Read-only discovery of a Copilot app (needs AWS creds, so captured earlier):" Enter
Type "#    ecsodus inventory --app my-app -o inventory.json" Enter
Sleep 1.5s
Type "ecsodus report inventory.json" Enter
Sleep 3s
Type "# What would a plain 'delete the stack' destroy?" Enter
Type "grep -o 'would destroy [0-9]* thing(s)' REPORT.md" Enter
Sleep 3s
Type "grep -m1 'With the retain patch' REPORT.md" Enter
Sleep 3s
Type "# 2. Terraform with import blocks + retain patches + a gated runbook" Enter
Type "ecsodus generate inventory.json --out infra/ --patch-bucket my-patch-bucket" Enter
Sleep 4s
Type "ls infra/" Enter
Sleep 2s
Type "grep -m3 -A3 '^import {' infra/my-app-test-fe-AddonsStack-1ABCDEFGHIJKL.tf" Enter
Sleep 4s
Type "grep '^## ' infra/RUNBOOK.md" Enter
Sleep 5s
