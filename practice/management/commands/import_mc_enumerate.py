# practice/management/commands/import_mc_enumerate.py
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from practice.models import Question, Tag

# Tokens we’ll scan for (handles nested enumerates)
TOKEN_RE = re.compile(
    r"(\\begin\{enumerate\}(\[(?P<opt>.*?)\]))"   # begin enumerate [options]
    r"|"
    r"(\\end\{enumerate\})"                       # end enumerate
    r"|"
    r"(^\\item(?:\s+|$))",                        # \item (line-start)
    flags=re.M
)

ALPH_ENUM_RE = re.compile(
    r"\\begin\{enumerate\}\s*\[label=\(\\Alph\*\)\](?P<body>[\s\S]*?)\\end\{enumerate\}",
    flags=re.S
)

def split_choices_from_body(body: str):
    """
    Choices inside the inner enumerate are often written on one line:
      \\item $-2$ \\item $-1/2$ ...
    So don't anchor at line start—split on any '\\item '.
    """
    parts = re.split(r"\\item\s+", body)
    parts = [p.strip() for p in parts if p.strip()]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return {letters[i]: parts[i] for i in range(min(len(parts), len(letters)))}

def infer_tags_from_filename(stem: str):
    # e.g., "Ch4_problems" -> ["Ch4", "problems"]
    bits = [b for b in re.split(r"[^\w]+", stem) if b]
    return bits

class Command(BaseCommand):
    help = "Import multiple-choice problems from LaTeX with outer A1/A2 enumerate and inner (A)(B)(C)(D)."

    def add_arguments(self, parser):
        parser.add_argument("path", type=str, help="Path to .tex file or directory")
        parser.add_argument("--tag", action="append", default=[], help="Extra tag(s) to attach")
        parser.add_argument("--dry-run", action="store_true", help="Parse and print summary without writing to DB")

    def handle(self, *args, **opts):
        root = Path(opts["path"]).resolve()
        if not root.exists():
            raise CommandError(f"Path not found: {root}")

        files = [root] if root.suffix.lower()==".tex" else sorted(root.rglob("*.tex"))
        if not files:
            self.stdout.write(self.style.WARNING("No .tex files found."))
            return

        User = get_user_model()
        created_by = User.objects.filter(is_superuser=True).first() or User.objects.first()
        if not created_by:
            raise CommandError("No users exist. Create one admin/user first.")

        total_created = 0
        total_detected = 0

        for f in files:
            tex = f.read_text(encoding="utf-8", errors="ignore")
            extra_tags = infer_tags_from_filename(f.stem) + opts["tag"]

            # Walk the document token-by-token, tracking enumerate nesting.
            stack = []               # each entry: {"label": "...raw options..."}
            current_item_start = None
            current_item_label  = None

            def active_label():
                return stack[-1]["label"] if stack else None

            # Collect all top-level problem items (those whose active label contains A\arabic*)
            problem_items = []

            for m in TOKEN_RE.finditer(tex):
                tok = m.group(0)
                if tok.startswith("\\begin{enumerate"):
                    stack.append({"label": m.group("opt") or ""})
                elif tok.startswith("\\end{enumerate}"):
                    # close current open problem item if we’re closing its level
                    if current_item_start is not None and current_item_label == active_label():
                        problem_items.append(tex[current_item_start:m.start()])
                        current_item_start = None
                        current_item_label = None
                    if stack:
                        stack.pop()
                else:
                    # \item
                    lbl = active_label() or ""
                    if "A\\arabic*" in lbl or "\\textbf{A\\arabic*" in lbl:
                        # We’re at a top-level problem item (A1/A2/…)
                        if current_item_start is not None:
                            problem_items.append(tex[current_item_start:m.start()])
                        current_item_start = m.end()
                        current_item_label  = lbl
                    else:
                        # ignore inner \item (choices)
                        pass

            # finalize last item (if file ended without closing)
            if current_item_start is not None:
                problem_items.append(tex[current_item_start:])

            self.stdout.write(f"{f.name}: found {len(problem_items)} problem(s).")
            total_detected += len(problem_items)

            # For each problem item, split stem and choices from inner enumerate
            for idx, item_text in enumerate(problem_items, 1):
                mm = ALPH_ENUM_RE.search(item_text)
                if mm:
                    stem_md = item_text[:mm.start()].strip()
                    choices = split_choices_from_body(mm.group("body"))
                    qtype = "choices"
                else:
                    stem_md = item_text.strip()
                    choices = {}
                    qtype = "open"

                if opts["dry_run"]:
                    # Show a tiny preview
                    prev = stem_md.replace("\n"," ")[:110]
                    self.stdout.write(f"  - P{idx}: {qtype}, choices={len(choices)} :: {prev}…")
                    continue

                # Skip exact duplicate stems (idempotent import)
                if Question.objects.filter(stem_md=stem_md).exists():
                    continue

                q = Question.objects.create(
                    type=qtype,
                    stem_md=stem_md,
                    choices=choices,
                    correct={},        # no key in the tex; fill later in admin if desired
                    created_by=created_by,
                )
                for tname in extra_tags:
                    t, _ = Tag.objects.get_or_create(name=tname)
                    q.tags.add(t)

                total_created += 1
                self.stdout.write(f"  ✔ Imported Q{q.id} ({qtype})")

        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS(f"Dry-run complete. Detected {total_detected} problem(s)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Created {total_created} question(s)."))
