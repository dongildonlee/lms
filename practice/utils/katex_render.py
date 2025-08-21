# practice/utils/katex_render.py
import re
import markdown

# We’ll use the markdown-katex extension
KATEX_EXT = 'markdown_katex'
KATEX_CFG = {
    # Critical for WeasyPrint: avoids inline <svg> that WeasyPrint struggles with
    'no_inline_svg': True,
    # Insert KaTeX fonts/CSS in the HTML once so the PDF has the right glyphs
    'insert_fonts_css': True,
}

# Your content uses plain $...$ and $$...$$. markdown-katex expects GitLab-style:
#   inline: $`...`$
#   block : ```math ... ```
INLINE_RE = re.compile(r'\$(.+?)\$', flags=re.S)           # $ ... $
BLOCK_RE  = re.compile(r'\$\$(.+?)\$\$', flags=re.S)       # $$ ... $$

def to_gitlab_math(md_text: str) -> str:
    def block_sub(m):  # $$...$$ -> ```math ... ```
        return '```math\n' + m.group(1).strip() + '\n```'
    def inline_sub(m): # $...$   -> $`...`$
        inner = m.group(1).strip()
        # avoid touching already converted $`...`$
        if inner.startswith('`') and inner.endswith('`'):
            return m.group(0)
        return '$`' + inner + '`$'

    # Do blocks first so inner $...$ aren’t double-processed
    out = BLOCK_RE.sub(block_sub, md_text)
    out = INLINE_RE.sub(inline_sub, out)
    return out

def render_md_with_katex(md_text: str) -> str:
    """Returns HTML where LaTeX has been rendered to KaTeX HTML (no JS needed)."""
    md = markdown.Markdown(
        extensions=['extra', KATEX_EXT],
        extension_configs={KATEX_EXT: KATEX_CFG}
    )
    return md.convert(to_gitlab_math(md_text))
