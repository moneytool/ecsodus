# Renders docs/assets/gates.gif: ecsodus's safety gates refusing unsafe steps.
#   uv run python tools/visuals/prepare_gates_demo.py /tmp/ecsodus-gates-demo
#   (cd /tmp/ecsodus-gates-demo/infra && vhs <repo>/docs/assets/gates.tape)
Output gates.gif
Set Shell "bash"
Set FontSize 15
Set Width 1240
Set Height 500
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 30ms

Hide
Type "export PS1='$ ' && ecsodus --version >/dev/null && clear" Enter
Sleep 2s
Show

Type "# Every mutating runbook step is gated. An import that would also UPDATE a database:" Enter
Type "ecsodus check plan-unsafe.json --manifest ecsodus-manifest.json --phase import | head -2" Enter
Sleep 3s
Type "# The real import plan: pure imports only, every expected ID present" Enter
Type "ecsodus check plan-import.json --manifest ecsodus-manifest.json --phase import" Enter
Sleep 3s
Type "# A retain-patch change set that sneaks in a property change:" Enter
Type "ecsodus check --changeset cs-unsafe.json --manifest ecsodus-manifest.json" Enter
Sleep 3s
Type "# The policy-only change set (DeletionPolicy / UpdateReplacePolicy: Retain):" Enter
Type "ecsodus check --changeset cs-retain.json --manifest ecsodus-manifest.json" Enter
Sleep 4s
