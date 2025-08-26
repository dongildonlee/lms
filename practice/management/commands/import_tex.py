# practice/management/commands/import_tex.py
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from practice.models import Question, Tag
from django.contrib.auth.models import User

# ----------------------- existing helpers you had -----------------------

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
    # soften \textbf to markdown-ish bold
    s = re.sub(r"\\textbf\{([^}]*)\}", r"**\1**", s)
    return _trim(s)

def _parse_nested_choices(block_text: str):
    """
    Inside an item's nested enumerate, split on top-level \item's to build choices.
    Ignore anything before the first \item (e.g. [label=(\Alph*)]).
    """
    parts = re.split(r"(?m)^\s*\\item\b", block_text)
    parts = parts[1:]  # drop anything before the first \item
    parts = [p for p in parts if p.strip()]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = {}
    for i, p in enumerate(parts):
        lab = letters[i] if i < len(letters) else str(i+1)
        out[lab] = _trim(p)
    return out

def _split_top_level_items(body: str):
    """
    Return (preamble, items) where preamble is everything before the first
    top-level \begin{enumerate}, and items are the top-level \item blocks.
    """
    m = re.search(r"\\begin\{enumerate\}", body)
    if not m:
        # no enumerate: treat whole body as "preamble"
        return body, []

    preamble = body[:m.start()]
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

    return preamble, [_trim(x) for x in items if x.strip()]

def _extract_item_stem_and_choices(item_text: str):
    """
    For one top-level \item block:
      - remove \answer{X} (capture X)
      - take first nested enumerate as choices
      - return (stem_without_that_enumerate, choices, answer_key)
    """
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

# ----------------------- NEW: asset & uses support -----------------------

ASSET_BLOCK_RE = re.compile(
    r"(?is)"                       # i: case-insensitive, s: dot matches newlines
    r"\\begin\{asset\}\{([^}]+)\}\s*"  # \begin{asset}{key}
    r"(.*?)"                            # content (non-greedy)
    r"\\end\{asset\}\s*"                # \end{asset}
)

USES_RE = re.compile(r"\\uses\{([^}]+)\}", re.I)

def _extract_assets_from_text(s: str):
    """
    Find and remove all \begin{asset}{key}...\end{asset} blocks in 's'.
    Return (text_without_assets, assets_dict).
    """
    assets = {}

    def repl(m):
        key = m.group(1).strip()
        content = _trim(m.group(2))
        assets[key] = content
        return ""  # strip from text

    cleaned = ASSET_BLOCK_RE.sub(repl, s or "")
    return _trim(cleaned), assets

def _remove_uses_and_collect_keys(s: str):
    """
    Remove all \uses{key} markers from 's' and return (cleaned_text, [keys]).
    """
    keys = USES_RE.findall(s or "")
    cleaned = USES_RE.sub("", s or "")
    return _trim(cleaned), [k.strip() for k in keys if k.strip()]

def _prepend_assets(stem: str, assets: dict, keys: list[str]) -> str:
    """
    Prepend the selected asset blocks (dedup, preserve first-seen order) to the stem.
    """
    seen = set()
    blocks = []
    for k in keys:
        if k not in seen and k in assets:
            blocks.append(assets[k])
            seen.add(k)
    if blocks:
        return _trim("\n\n".join(blocks + [stem]))
    return stem

# ----------------------- File → Question dicts -----------------------

def parse_tex_file_to_questions(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # meta headers (optional "%% key: value")
    meta, body_start = {}, 0
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line.strip())
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
        else:
            body_start = i
            break

    body = "\n".join(lines[body_start:]).strip()

    # Split into preamble + items (preamble = everything before the first top-level enumerate)
    preamble, items = _split_top_level_items(body)

    # NEW: extract shared assets from the preamble only (do NOT dump whole preamble into each item)
    preamble_wo_assets, assets = _extract_assets_from_text(preamble)

    # Tags and type from headers (unchanged)
    tags = [t.strip() for t in (meta.get("tags", "").strip().strip("[]")).split(",") if t.strip()]
    qtype = (meta.get("type") or "mcq").lower()

    if items:
        out = []
        for it in items:
            # Pull stem/choices/answer from the item
            stem, choices, ans_inline = _extract_item_stem_and_choices(it)

            # NEW: strip \uses{key} markers from the item stem and collect requested assets
            stem_no_uses, use_keys = _remove_uses_and_collect_keys(stem)

            # NEW: only prepend assets actually referenced by this item
            full_stem = _prepend_assets(stem_no_uses, assets, use_keys)

            # If you still want to include *non-asset* bits of preamble for every item, append them here:
            # (most folks leave this out to avoid accidental leaks)
            # if preamble_wo_assets:
            #     full_stem = _trim(preamble_wo_assets + "\n\n" + full_stem)

            correct = (ans_inline or meta.get("answer") or "A").strip().upper()[:1]
            out.append({
                "type": qtype,
                "tags": tags,
                "answer": correct,
                "stem_tex": full_stem,      # store with ONLY relevant assets included
                "choices": choices or None,
            })
        return out

    # Single-question fallback (no enumerate at top level)
    # We still respect asset markers in the whole body
    body_wo_assets, assets = _extract_assets_from_text(body)
    stem = _strip_comments_and_textmode_macros(body_wo_assets)
    return [{
        "type": qtype,
        "tags": tags,
        "answer": (meta.get("answer") or "A").strip().upper()[:1],
        "stem_tex": stem,
        "choices": None
    }]

# ----------------------- Management command -----------------------

class Command(BaseCommand):
    help = "Import LaTeX questions from a folder (supports shared assets via \\begin{asset}{key}... and per-item \\uses{key})."

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
                    stem_md=data["stem_tex"],      # your model stores TeX in 'stem_md'
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

