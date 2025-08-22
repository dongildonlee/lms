# practice/management/commands/import_tex.py
import re, json
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from practice.models import Question, Tag
from django.contrib.auth.models import User

HEADER_RE = re.compile(r"^%%\s*(\w+)\s*:\s*(.+)$")
CHOICE_MACRO_RE = re.compile(r"\\choice\[(?P<key>[A-Z])\]\{(?P<label>.+?)\}", re.S)

# tokens for enumerate parsing
ENUM_TOKEN_RE = re.compile(
    r"(\\begin\{enumerate\})|(\\end\{enumerate\})|(\\item\b)",
    re.M
)

def _strip_answer_marker(s):
    """
    Optional inline correct marker: \answer{C}
    Returns (text_without_marker, answer_or_None)
    """
    m = re.search(r"\\answer\{([A-Z])\}", s)
    if not m:
        return s, None
    ans = m.group(1)
    s = s[:m.start()] + s[m.end():]
    return s, ans

def _trim(s):
    return re.sub(r"\s+\Z", "", re.sub(r"\A\s+", "", s or ""))

def _parse_nested_choices(block_text):
    """
    Given the text inside an item's nested \begin{enumerate}...\end{enumerate},
    split \item choices and return an ordered dict-like { 'A': '...', 'B': '...', ... }.
    """
    # split on \item at line starts, keep content until next \item or end
    parts = re.split(r"(?m)^\s*\\item\b", block_text)
    parts = [p for p in parts if p.strip()]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = {}
    for i, p in enumerate(parts):
        lab = letters[i] if i < len(letters) else str(i+1)
        out[lab] = _trim(p)
    return out

def _split_top_level_items(body):
    """
    Find the FIRST \begin{enumerate}...\end{enumerate} block in 'body',
    then split its TOP-LEVEL \item's into item strings.

    Returns (preamble_text, [item_text_1, item_text_2, ...]).
    Preamble is the text before the first \begin{enumerate}.
    """
    # locate first enumerate begin
    m = re.search(r"\\begin\{enumerate\}", body)
    if not m:
        return body, []  # no enumerate found

    preamble = body[:m.start()]
    enum_start = m.start()

    # scan tokens to find matching \end{enumerate} and top-level \item boundaries
    depth = 0
    items = []
    current_start = None
    end_index = None

    for tok in ENUM_TOKEN_RE.finditer(body, enum_start):
        beg, end, item = tok.groups()
        if beg:
            depth += 1
            # after we see the first begin, look for items at depth==1
            continue
        if end:
            # closing an enumerate
            if depth == 1:
                # we are closing the outer enumerate: finalize last item
                if current_start is not None:
                    items.append(body[current_start:tok.start()])
                    current_start = None
                end_index = tok.end()
                depth -= 1
                break
            depth -= 1
            continue
        if item:
            # \item at current depth
            if depth == 1:
                if current_start is not None:
                    # finish previous item
                    items.append(body[current_start:tok.start()])
                current_start = tok.end()
            continue

    # if we never hit end of outer enumerate, but had items, close with end of body
    if current_start is not None and (end_index is None):
        items.append(body[current_start:len(body)])

    return preamble, [ _trim(x) for x in items if x.strip() ]

def _extract_item_stem_and_choices(item_text):
    """
    Split an item's text into 'stem' (before first nested enumerate)
    and 'choices' dict (from the first nested enumerate block), if present.
    """
    m = re.search(r"\\begin\{enumerate\}", item_text)
    if not m:
        # no nested choices enumerate
        stem, ans = _strip_answer_marker(item_text)
        return _trim(stem), {}, ans

    stem = item_text[:m.start()]
    rest = item_text[m.start():]

    # find the matching end for this nested enumerate
    # simple depth counter just within 'rest'
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

def parse_tex_file_to_questions(path: Path):
    """
    Return a LIST of question dicts extracted from a .tex file.

    Supports two formats:

    (A) Single-question file with optional headers and \choice[...] macros.
        %% type: mcq
        %% tags: Statistics, Probability
        %% answer: C
        <body with \choice[A]{...} etc.>

    (B) One top-level \begin{enumerate}...\end{enumerate} with many \item,
        each optionally containing a nested enumerate for choices.
        Any preamble (e.g., a table) before the enumerate is prepended to each stem.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # parse meta headers at top
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
    tags = []
    raw_tags = meta.get("tags", "")
    if raw_tags:
        raw = raw_tags.strip().strip("[]")
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    qtype = (meta.get("type") or "mcq").lower()

    # (B) Try multi-question enumerate first
    preamble, items = _split_top_level_items(body)
    if items:
        out = []
        for it in items:
            stem, choices, ans_inline = _extract_item_stem_and_choices(it)
            # prepend preamble (table, etc.) to each stem so each item is self-contained
            full_stem = _trim((preamble or "") + "\n\n" + stem) if preamble.strip() else _trim(stem)
            correct = (ans_inline or meta.get("answer") or "A").strip().upper()[:1]
            out.append({
                "type": qtype,
                "tags": tags,
                "answer": correct,
                "stem_tex": full_stem,
                "choices": choices or None,
            })
        return out

    # (A) Fallback: single-question file with \choice[...] macros
    choices = {}
    for m in CHOICE_MACRO_RE.finditer(body):
        key = m.group("key").strip()
        label = _trim(m.group("label"))
        choices[key] = label

    # allow inline \answer{C} in single files as well
    body_no_ans, ans_inline = _strip_answer_marker(body)

    return [{
        "type": qtype,
        "tags": tags,
        "answer": (ans_inline or meta.get("answer") or "A").strip().upper()[:1],
        "stem_tex": _trim(body_no_ans),
        "choices": choices or None,
    }]

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
                self.stdout.write(self.style.WARNING(
                    f"User {opts['created_by']} not found; leaving created_by null."
                ))

        files = list(root.rglob("*.tex"))
        if not files:
            self.stdout.write("No .tex files found.")
            return

        total = 0
        for f in files:
            questions = parse_tex_file_to_questions(f)
            for data in questions:
                q = Question.objects.create(
                    type=data["type"],
                    stem_md=data["stem_tex"],           # MathJax-friendly TeX in web
                    choices=data["choices"] or {},      # used by MCQ UI
                    correct={"choice": data["answer"]}, # default if not specified
                    created_by=created_by,
                )
                for tag_name in data["tags"]:
                    t, _ = Tag.objects.get_or_create(name=tag_name)
                    q.tags.add(t)
                total += 1
                self.stdout.write(f"Imported Q{q.id} from {f.relative_to(root)}")
        self.stdout.write(self.style.SUCCESS(f"Done. Imported {total} question(s)."))
