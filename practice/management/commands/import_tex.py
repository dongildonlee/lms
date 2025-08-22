# practice/management/commands/import_tex.py
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from practice.models import Question, Tag
from django.contrib.auth.models import User

HEADER_RE = re.compile(r"^%%\s*(\w+)\s*:\s*(.+)$")
ENUM_TOKEN_RE = re.compile(r"(\\begin\{enumerate\})|(\\end\{enumerate\})|(\\item\b)", re.M)

def _trim(s: str) -> str:
    return re.sub(r"\s+\Z", "", re.sub(r"\A\s+", "", s or ""))

def _strip_answer_marker(s):
    m = re.search(r"\\answer\{([A-Z])\}", s)
    if not m:
        return s, None
    ans = m.group(1)
    return s[:m.start()] + s[m.end():], ans

def _strip_comments_and_textmode_macros(s: str) -> str:
    # drop lines that are pure TeX comments
    lines = [ln for ln in (s or "").splitlines() if not ln.strip().startswith("%")]
    s = "\n".join(lines)
    # strip common text-mode spacing/formatting macros that don't display in the web
    s = re.sub(r"\\noindent\b", "", s)
    s = re.sub(r"\\(big|med|small)skip\b", "", s)
    # leave \textbf inside math; outside math it will show literally, so soften it:
    s = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", s)  # simple and good enough here
    return _trim(s)

def _parse_nested_choices(block_text):
    """
    Return {'A': '...', 'B': '...', ...} from a nested enumerate.
    Ignores any text before the first \item (e.g. [label=(\Alph*)]).
    """
    items = re.findall(
        r"(?ms)^\s*\\item\b(.*?)(?=^\s*\\item\b|\\end\{enumerate\})",
        block_text
    )
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = {}
    for i, p in enumerate(items):
        out[letters[i]] = _trim(p)
    return out




def _split_top_level_items(body: str):
    """
    Find the FIRST top-level enumerate and split into item strings.
    Returns (preamble_text, [item_text1, item_text2, ...]).
    """
    m = re.search(r"\\begin\{enumerate\}", body)
    if not m:
        # No enumerate: treat whole body as preamble
        return _trim(body), []

    preamble = body[:m.start()]
    enum_start = m.start()

    depth = 0
    items, current_start, end_index = [], None, None

    for tok in ENUM_TOKEN_RE.finditer(body, enum_start):
        beg, end, item = tok.groups()
        if beg:
            depth += 1
            continue
        if end:
            if depth == 1:
                if current_start is not None:
                    items.append(body[current_start:tok.start()])
                    current_start = None
                end_index = tok.end()
                depth -= 1
                break
            depth -= 1
            continue
        if item and depth == 1:
            if current_start is not None:
                items.append(body[current_start:tok.start()])
            current_start = tok.end()

    if current_start is not None and end_index is None:
        items.append(body[current_start:len(body)])

    return _trim(preamble), [_trim(x) for x in items if x.strip()]


def _extract_item_stem_and_choices(item_text: str):
    m = re.search(r"\\begin\{enumerate\}", item_text)
    if not m:
        stem, ans = _strip_answer_marker(item_text)
        return _strip_comments_and_textmode_macros(stem), {}, ans

    stem_raw = item_text[:m.start()]
    rest = item_text[m.start():]

    depth = 0
    start_idx = end_idx = None
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

    stem_raw, ans = _strip_answer_marker(stem_raw)
    stem = _strip_comments_and_textmode_macros(stem_raw)
    return stem, choices, ans

def parse_tex_file_to_questions(path: Path):
    """
    Return a LIST of question dicts extracted from a .tex file.

    Supports:
      (B) One top-level \begin{enumerate}...\end{enumerate} with many \item,
          where any preamble (e.g., a TikZ table) that precedes the enumerate
          is PREPENDED to EVERY item's stem.
      (A) Single-question file with optional \choice[...] macros and \answer{C}.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # --- meta headers (optional: "%% key: value")
    meta, body_start = {}, 0
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            body_start = i
            break

    body = "\n".join(lines[body_start:]).strip()

    # tags
    tags = []
    raw_tags = meta.get("tags", "")
    if raw_tags:
        raw = raw_tags.strip().strip("[]")
        tags = [t.strip() for t in raw.split(",") if t.strip()]

    qtype = (meta.get("type") or "mcq").lower()

    # --- (B) multi-question enumerate: keep the PREAMBLE
    preamble, items = _split_top_level_items(body)
    if items:
        out = []
        for it in items:
            stem, choices, ans_inline = _extract_item_stem_and_choices(it)
            # prepend preamble (table/tikz/etc.) so each item is self-contained
            full_stem = _trim((preamble + "\n\n" + stem) if preamble else stem)
            correct = (ans_inline or meta.get("answer") or "A").strip().upper()[:1]
            out.append({
                "type": qtype,
                "tags": tags,
                "answer": correct,
                "stem_tex": full_stem,
                "choices": choices or None,
            })
        return out

    # --- (A) single-question fallback with \choice[...] and optional \answer{C}
    choices = {}
    for m in CHOICE_MACRO_RE.finditer(body):
        key = m.group("key").strip()
        label = _trim(m.group("label"))
        choices[key] = label

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
                self.stdout.write(self.style.WARNING(f"User {opts['created_by']} not found; leaving created_by null."))

        files = list(root.rglob("*.tex"))
        if not files:
            self.stdout.write("No .tex files found.")
            return

        total = 0
        for f in files:
            for data in parse_tex_file_to_questions(f):
                q = Question.objects.create(
                    type=data["type"],
                    stem_md=data["stem_tex"],
                    choices=data["choices"] or {},
                    correct={"choice": data["answer"]},
                    created_by=created_by,
                )
                for tag_name in data["tags"]:
                    t, _ = Tag.objects.get_or_create(name=tag_name)
                    q.tags.add(t)
                total += 1
                self.stdout.write(f"Imported Q{q.id} from {f.relative_to(root)}")

        self.stdout.write(self.style.SUCCESS(f"Done. Imported {total} question(s)."))
