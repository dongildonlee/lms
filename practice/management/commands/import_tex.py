# practice/management/commands/import_tex.py
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from practice.models import Question, Tag

# ---------------------------------------------------------------------------
# Header metadata lines (optional, at very top of file)
#   %% type: mcq
#   %% tags: Statistics, Probability
#   %% answer: C
# ---------------------------------------------------------------------------
HEADER_RE = re.compile(r"^%%\s*(\w+)\s*:\s*(.+)$")

# Single-question macro-style choices (fallback format)
CHOICE_MACRO_RE = re.compile(r"\\choice\[(?P<key>[A-Z])\]\{(?P<label>.+?)\}", re.S)

# Robust enumerate tokenization (allowing optional [...] after begin)
OPEN_ENUM = re.compile(r"\\begin\{enumerate\}(?:\[[^\]]*\])?")
CLOSE_ENUM = re.compile(r"\\end\{enumerate\}")
ENUM_TOKEN_RE = re.compile(
    r"(\\begin\{enumerate\}(?:\[[^\]]*\])?)|(\\end\{enumerate\})|(\\item\b)",
    re.M,
)

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _trim(s: str) -> str:
    return re.sub(r"\s+\Z", "", re.sub(r"\A\s+", "", s or ""))


def _strip_answer_marker(s: str):
    """
    Remove optional inline \\answer{C}. Returns (text_without_marker, 'C' or None).
    """
    m = re.search(r"\\answer\{([A-Z])\}", s)
    if not m:
        return s, None
    ans = m.group(1)
    s = s[:m.start()] + s[m.end():]
    return s, ans


def _document_body(text: str) -> str:
    """
    If the file is a full LaTeX doc, keep only the content between
    \\begin{document} ... \\end{document}. Otherwise return text unchanged.
    """
    m = re.search(r"\\begin{document}(.*)\\end{document}", text, re.S)
    return m.group(1).strip() if m else text


def _parse_nested_choices(block_text: str) -> dict:
    """
    Given the text inside an item's nested enumerate, split top-level \\item's
    into an ordered { 'A': '...', 'B': '...', ... } dict.
    """
    parts = re.split(r"(?m)^\s*\\item\b", block_text)
    parts = [p for p in parts if p.strip()]
    out = {}
    for i, p in enumerate(parts):
        lab = LETTERS[i] if i < len(LETTERS) else str(i + 1)
        out[lab] = _trim(p)
    return out


def _split_top_level_items(body: str):
    """
    Find the FIRST top-level enumerate in 'body' and split its top-level \\item's.
    Returns (preamble_text, [item_text_1, ...]).
    """
    m = OPEN_ENUM.search(body)
    if not m:
        return body, []  # no enumerate found

    preamble = body[: m.start()]
    enum_start = m.start()

    depth = 0
    items = []
    current_start = None
    end_index = None

    for tok in ENUM_TOKEN_RE.finditer(body, enum_start):
        beg, end, item = tok.groups()

        if beg:
            depth += 1
            continue

        if end:
            if depth == 1:
                # close the outer enumerate
                if current_start is not None:
                    items.append(body[current_start : tok.start()])
                    current_start = None
                end_index = tok.end()
                depth -= 1
                break
            depth -= 1
            continue

        if item and depth == 1:
            if current_start is not None:
                items.append(body[current_start : tok.start()])
            current_start = tok.end()

    if current_start is not None and end_index is None:
        items.append(body[current_start : len(body)])

    return preamble, [_trim(x) for x in items if x.strip()]


def _extract_item_stem_and_choices(item_text: str):
    """
    For one \\item:
      - stem = text before first nested enumerate
      - choices = from first nested enumerate (if present)
      - answer = optional inline \\answer{C} in the stem
    """
    m = OPEN_ENUM.search(item_text)
    if not m:
        stem, ans = _strip_answer_marker(item_text)
        return _trim(stem), {}, ans

    stem = item_text[: m.start()]
    rest = item_text[m.start() :]

    depth = 0
    start_idx = None
    end_idx = None
    for tok in ENUM_TOKEN_RE.finditer(rest):
        beg, end, itm = tok.groups()
        if beg:
            depth += 1
            if depth == 1:
                start_idx = tok.end()
        elif end:
            if depth == 1:
                end_idx = tok.start()
                break
            depth -= 1

    choices = {}
    if start_idx is not None and end_idx is not None:
        choices_block = rest[start_idx:end_idx]
        choices = _parse_nested_choices(choices_block)

    stem, ans = _strip_answer_marker(stem)
    return _trim(stem), choices, ans


def parse_tex_file_to_questions(path: Path) -> list[dict]:
    """
    Extract a list of question dicts from a .tex file.

    Supports:
      (A) One top-level enumerate with many \\item's (each may contain a nested
          enumerate for choices). Preamble before the enumerate (e.g., a table)
          is prepended to every item's stem.
      (B) A single-question body that may use \\choice[A]{...} macros.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Parse optional "%% key: value" headers at the very top
    meta = {}
    body_start = 0
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            body_start = i
            break

    body = "\n".join(lines[body_start:]).strip()
    body = _document_body(body)  # keep only content within \begin{document}...\end{document}

    # Tags (comma-list or [list])
    tags = []
    raw_tags = meta.get("tags", "")
    if raw_tags:
        raw = raw_tags.strip().strip("[]")
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    qtype = (meta.get("type") or "mcq").lower()

    # (A) Prefer multi-question enumerate
    preamble, items = _split_top_level_items(body)
    if items:
        out = []
        pre = _trim(preamble)
        for it in items:
            stem, choices, ans_inline = _extract_item_stem_and_choices(it)
            full_stem = _trim((pre + "\n\n" + stem) if pre else stem)
            correct = (ans_inline or meta.get("answer") or "A").strip().upper()[:1]
            out.append(
                {
                    "type": qtype,
                    "tags": tags,
                    "answer": correct,
                    "stem_tex": full_stem,
                    "choices": choices or None,
                }
            )
        return out

    # (B) Single-question macro format
    choices = {}
    for m in CHOICE_MACRO_RE.finditer(body):
        key = m.group("key").strip()
        label = _trim(m.group("label"))
        choices[key] = label

    body_no_ans, ans_inline = _strip_answer_marker(body)
    return [
        {
            "type": qtype,
            "tags": tags,
            "answer": (ans_inline or meta.get("answer") or "A").strip().upper()[:1],
            "stem_tex": _trim(body_no_ans),
            "choices": choices or None,
        }
    ]


# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Import LaTeX questions from a folder (recursively)."

    def add_arguments(self, parser):
        parser.add_argument("root", type=str, help="Folder containing .tex files")
        parser.add_argument(
            "--created-by", type=str, default=None, help="Username to set as author"
        )

    def handle(self, *args, **opts):
        root = Path(opts["root"]).expanduser().resolve()
        if not root.exists():
            raise CommandError(f"{root} does not exist")

        created_by = None
        if opts["created_by"]:
            try:
                created_by = User.objects.get(username=opts["created_by"])
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f"User {opts['created_by']} not found; leaving created_by null."
                    )
                )

        files = list(root.rglob("*.tex"))
        if not files:
            self.stdout.write("No .tex files found.")
            return

        total = 0
        for f in files:
            try:
                questions = parse_tex_file_to_questions(f)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Parse error in {f}: {e}"))
                continue

            for data in questions:
                q = Question.objects.create(
                    type=data["type"],
                    stem_md=data["stem_tex"],            # MathJax-friendly TeX on web
                    choices=data["choices"] or {},       # multiple-choice options
                    correct={"choice": data["answer"]},  # simple MCQ key
                    created_by=created_by,
                )
                for tag_name in data["tags"]:
                    t, _ = Tag.objects.get_or_create(name=tag_name)
                    q.tags.add(t)

                total += 1
                self.stdout.write(f"Imported Q{q.id} from {f.relative_to(root)}")

        self.stdout.write(self.style.SUCCESS(f"Done. Imported {total} question(s)."))
