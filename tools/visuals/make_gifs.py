"""Render the README animations (docs/assets/how-it-works.gif, docs/assets/retain-patch.gif).

    uv run --with pillow python tools/visuals/make_gifs.py

Deterministic: same input, same frames. Fonts come from macOS system paths with a Pillow
fallback, so the script also runs elsewhere (with plainer type).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[2] / "docs" / "assets"
W, H = 1000, 470

BG = (15, 23, 42)  # slate-900
PANEL = (30, 41, 59)  # slate-800
MUTED = (100, 116, 139)  # slate-500
TEXT = (226, 232, 240)  # slate-200
ORANGE = (255, 153, 0)  # AWS
GREEN = (34, 197, 94)
RED = (239, 68, 68)
PURPLE = (123, 66, 188)  # Terraform
BLUE = (56, 189, 248)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (["/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else []) + [
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def mono(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def centered(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, f, fill) -> None:
    x0, y0, x1, y1 = box
    lines = text.split("\n")
    heights = [d.textbbox((0, 0), ln, font=f)[3] for ln in lines]
    total = sum(heights) + 6 * (len(lines) - 1)
    y = y0 + (y1 - y0 - total) / 2
    for ln, h in zip(lines, heights, strict=True):
        w = d.textlength(ln, font=f)
        d.text((x0 + (x1 - x0 - w) / 2, y), ln, font=f, fill=fill)
        y += h + 6


def save(frames: list[Image.Image], durations: list[int], name: str) -> Path:
    path = OUT / name
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=64) for f in frames]
    pal[0].save(
        path,
        save_all=True,
        append_images=pal[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    return path


# -- 1. How it works -------------------------------------------------------------------------
STEPS = [
    (
        "1",
        "Inventory",
        "read-only",
        "Reads every Copilot stack, template and live resource.\n"
        "Only Describe / List / Get calls. Secret values are never read.",
    ),
    (
        "2",
        "Report",
        "readiness",
        "Shows what a plain stack delete would destroy (ALB, NAT, EFS, certs),\n"
        "and which stacks can hand off. Unsupported parts stay on Copilot.",
    ),
    (
        "3",
        "Generate",
        "Terraform + runbook",
        "Terraform with import blocks of the exact deployed values,\n"
        "retain-patched templates, and a fail-fast RUNBOOK.md.",
    ),
    (
        "4",
        "Retain-patch",
        "every resource",
        "DeletionPolicy: Retain on every resource of every stack.\n"
        "check --changeset accepts the change set only if it is policy-only.",
    ),
    (
        "5",
        "Import + teardown",
        "gated",
        "Plan is 44/44 pure imports -> apply -> zero-change plan ->\n"
        "Copilot stacks deleted. Nothing removed, no Delete handler runs.",
    ),
]


def how_it_works_frame(active: int, progress: float) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text(
        (40, 28),
        "How ecsodus migrates an AWS Copilot app to Terraform, in place",
        font=font(26, True),
        fill=TEXT,
    )
    d.text(
        (40, 66),
        "no traffic moves  ·  every resource imported  ·  stacks deleted safely",
        font=font(17),
        fill=MUTED,
    )
    bw, bh, gap, top = 164, 112, 26, 120
    left = (W - (5 * bw + 4 * gap)) // 2
    for i, (num, title, sub, _) in enumerate(STEPS):
        x = left + i * (bw + gap)
        done, cur = i < active, i == active
        fill = (22, 101, 52) if done else (PANEL if not cur else (66, 47, 16))
        outline = GREEN if done else (ORANGE if cur else MUTED)
        d.rounded_rectangle(
            (x, top, x + bw, top + bh), radius=14, fill=fill, outline=outline, width=3 if cur else 2
        )
        badge = GREEN if done else (ORANGE if cur else MUTED)
        d.ellipse((x + 12, top + 12, x + 40, top + 40), fill=badge)
        if done:  # drawn, not a glyph: system fonts may lack U+2713
            d.line([(x + 19, top + 26), (x + 24, top + 32), (x + 33, top + 19)], fill=BG, width=3)
        else:
            centered(d, (x + 12, top + 12, x + 40, top + 40), num, font(16, True), BG)
        tf = font(18 if len(title) < 15 else 16, True)
        centered(d, (x, top + 34, x + bw, top + 84), title, tf, TEXT)
        centered(d, (x, top + 78, x + bw, top + 104), sub, font(14), MUTED if not cur else ORANGE)
        if i < 4:
            ax = x + bw + 4
            col = GREEN if done else MUTED
            d.line((ax, top + bh / 2, ax + gap - 8, top + bh / 2), fill=col, width=3)
            d.polygon(
                [
                    (ax + gap - 8, top + bh / 2 - 6),
                    (ax + gap - 2, top + bh / 2),
                    (ax + gap - 8, top + bh / 2 + 6),
                ],
                fill=col,
            )
    # detail panel
    d.rounded_rectangle((40, 262, W - 40, 384), radius=14, fill=PANEL)
    if active < len(STEPS):
        step = STEPS[active]
        d.text((64, 276), f"Step {step[0]}: {step[1]}", font=font(19, True), fill=ORANGE)
        d.multiline_text((64, 306), step[3], font=font(17), fill=TEXT, spacing=8)
        d.rounded_rectangle((64, 366, W - 64, 371), radius=3, fill=(51, 65, 85))
        d.rounded_rectangle((64, 366, 64 + (W - 128) * progress, 371), radius=3, fill=ORANGE)
    else:
        d.text((64, 276), "Verified on real AWS (2026-09-30)", font=font(19, True), fill=GREEN)
        d.multiline_text(
            (64, 306),
            "44/44 pure imports  ·  all Copilot stacks deleted  ·  "
            "HTTP 200 throughout\nzero data loss  ·  "
            "Retain stopped every custom-resource Delete handler",
            font=font(17),
            fill=TEXT,
            spacing=8,
        )
    # footer: owners
    owner = "CloudFormation (Copilot)" if active < 4 else "Terraform"
    col = ORANGE if active < 4 else PURPLE
    label = "Owner of your infrastructure:"
    d.text((40, 404), label, font=font(16), fill=MUTED)
    ox = 40 + d.textlength(label, font=font(16)) + 12
    d.rounded_rectangle(
        (ox, 398, ox + 16 + d.textlength(owner, font=font(16, True)), 428), radius=8, fill=col
    )
    d.text((ox + 8, 404), owner, font=font(16, True), fill=(255, 255, 255))
    d.text((W - 300, 432), "github.com/moneytool/ecsodus", font=font(15), fill=MUTED)
    return img


def make_how_it_works() -> Path:
    frames, durations = [], []
    for step in range(len(STEPS)):
        for k in range(6):
            frames.append(how_it_works_frame(step, (k + 1) / 6))
            durations.append(420)
    frames.append(how_it_works_frame(len(STEPS), 1.0))
    durations.append(3500)
    return save(frames, durations, "how-it-works.gif")


# -- 2. Why retain patches -------------------------------------------------------------------
RESOURCES = [
    "Load balancer",
    "NAT gateways",
    "EFS file system",
    "DynamoDB table",
    "ACM certificate",
    "ECS service",
]


def retain_frame(phase: int, k: int) -> Image.Image:
    """phase 0: intact, 1: delete-stack, 2: consequences (k = how many resolved), 3: hold."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((40, 24), "Deleting the Copilot CloudFormation stacks", font=font(26, True), fill=TEXT)
    d.text(
        (40, 60),
        "A plain stack delete removes everything, and Copilot's custom resources add to it.",
        font=font(16),
        fill=MUTED,
    )
    cols = [
        (40, "As-is: aws cloudformation delete-stack", False),
        (520, "After ecsodus: every resource retained", True),
    ]
    for x, title, safe in cols:
        d.text((x, 96), title, font=font(18, True), fill=GREEN if safe else RED)
        # container: the stack, or Terraform state afterwards
        top, cw, ch = 128, 440, 252
        if phase == 0:
            d.rounded_rectangle((x, top, x + cw, top + ch), radius=12, outline=ORANGE, width=3)
            d.text(
                (x + 14, top + 8),
                "CloudFormation stack (Copilot)",
                font=font(14, True),
                fill=ORANGE,
            )
        elif phase == 1:
            d.rounded_rectangle(
                (x, top, x + cw, top + ch), radius=12, outline=(120, 70, 0), width=2
            )
            d.text(
                (x + 14, top + 8), "delete-stack in progress ...", font=font(14, True), fill=ORANGE
            )
        elif safe:
            d.rounded_rectangle((x, top, x + cw, top + ch), radius=12, outline=PURPLE, width=3)
            d.text(
                (x + 14, top + 8),
                "Terraform state (imported in place)",
                font=font(14, True),
                fill=(180, 140, 230),
            )
        else:
            d.text((x + 14, top + 8), "stack deleted", font=font(14, True), fill=MUTED)
        for i, name in enumerate(RESOURCES):
            r, c = divmod(i, 2)
            bx, by = x + 16 + c * 212, top + 38 + r * 68
            resolved = phase == 3 or (phase == 2 and i < k)
            if resolved and not safe:
                fill, edge, label = (69, 10, 10), RED, "deleted"
            elif resolved and safe:
                fill, edge, label = (20, 83, 45), GREEN, "kept"
            else:
                fill, edge, label = PANEL, MUTED, ""
            d.rounded_rectangle(
                (bx, by, bx + 200, by + 56), radius=10, fill=fill, outline=edge, width=2
            )
            d.text(
                (bx + 12, by + 8),
                name,
                font=font(16, True),
                fill=TEXT if not (resolved and not safe) else (252, 165, 165),
            )
            if label:
                d.text((bx + 12, by + 31), label, font=font(14), fill=edge)
            if resolved and not safe:
                d.line(
                    (bx + 10, by + 19, bx + 12 + d.textlength(name, font=font(16, True)), by + 19),
                    fill=RED,
                    width=2,
                )
    if phase == 3:
        d.text(
            (40, 396), "Service down · data and certificates gone", font=font(18, True), fill=RED
        )
        d.text(
            (520, 396),
            "Service up · data intact · now in Terraform",
            font=font(18, True),
            fill=GREEN,
        )
    d.text(
        (40, 432),
        "Verified on real AWS: Retain stops Copilot's custom-resource Delete handlers.",
        font=font(15),
        fill=MUTED,
    )
    return img


def make_retain_patch() -> Path:
    frames, durations = [retain_frame(0, 0)], [1800]
    frames.append(retain_frame(1, 0))
    durations.append(1300)
    for k in range(1, len(RESOURCES) + 1):
        frames.append(retain_frame(2, k))
        durations.append(520)
    frames.append(retain_frame(3, 0))
    durations.append(4200)
    return save(frames, durations, "retain-patch.gif")


if __name__ == "__main__":
    for p in (make_how_it_works(), make_retain_patch()):
        print(f"wrote {p.relative_to(OUT.parents[1])} ({p.stat().st_size // 1024} KiB)")
