# practice/management/commands/import_tex.py
import re, json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from practice.models import Question, Tag
from django.contrib.auth.models import User

HEADER_RE = re.compile(r"^%%\s*(\w+)\s*:\s*(.+)$")
CHOICE_RE = re.compile(r"\\choice\[(?P<key>[A-Z])\]\{(?P<label>.+?)\}", re.S)

def parse_tex(path: Path):
    """Return dict with type, tags(list), answer, stem_tex(str), choices(dict)."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    meta = {}
    body_start = 0
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            # first non-header line marks start of body
            body_start = i
            break

    body = "\n".join(lines[body_start:]).strip()

    # choices: optional
    choices = {}
    for m in CHOICE_RE.finditer(body):
        key = m.group("key").strip()
        label = m.group("label").strip()
        choices[key] = label

    # tags: comma or bracket separated
    tags = []
    raw_tags = meta.get("tags", "")
    if raw_tags:
        # allow "A, B" or "[A, B]"
        raw = raw_tags.strip().strip("[]")
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    return {
        "type": meta.get("type", "mcq").lower(),
        "tags": tags,
        "answer": meta.get("answer", "A").strip().upper(),
        "stem_tex": body,
        "choices": choices or None,
    }

class Command(BaseCommand):
    help = "Import LaTeX questions from a folder"

    def add_arguments(self, parser):
        parser.add_argument("root", type=str, help="Folder containing .tex files")
        parser.add_argument("--created-by", type=str, default=None, help="Username to set as author")

    def handle(self, *args, **opts):
        root = Path(opts["root"]).expanduser().resolve()
        if not root.exists():
            raise CommandError(f"{root} does not exist")

        created_by = None
        if opts["created_by"]:
            try:
                created_by = User.objects.get(username=opts["created_by"])
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"User {opts['created_by']} not found; leaving created_by null."))

        files = list(root.rglob("*.tex"))
        if not files:
            self.stdout.write("No .tex files found.")
            return

        count = 0
        for f in files:
            data = parse_tex(f)
            q = Question.objects.create(
                type=data["type"],
                stem_md=data["stem_tex"],      # MathJax can render this on the web
                choices=data["choices"] or {}, # still used by your POC UI
                correct={"choice": data["answer"]},
                created_by=created_by,
            )
            # attach tags
            for tag_name in data["tags"]:
                t, _ = Tag.objects.get_or_create(name=tag_name)
                q.tags.add(t)
            count += 1
            self.stdout.write(f"Imported Q{q.id} from {f.relative_to(root)}")

        self.stdout.write(self.style.SUCCESS(f"Done. Imported {count} question(s)."))
