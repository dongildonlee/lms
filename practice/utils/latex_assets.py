import os, shutil, subprocess, tempfile, textwrap, logging
from django.conf import settings
log = logging.getLogger(__name__)

def _find_exe(name: str):
    # Prefer vendored binaries in ./bin, else PATH
    here_bin = os.path.join(settings.BASE_DIR, "bin", name)
    if os.path.isfile(here_bin) and os.access(here_bin, os.X_OK):
        return here_bin
    return shutil.which(name)

def _tectonic():
    exe = _find_exe("tectonic")
    if not exe:
        raise RuntimeError("tectonic binary not found")
    return exe

def _pdftocairo():
    exe = _find_exe("pdftocairo")
    if not exe:
        raise RuntimeError("pdftocairo not found (install poppler-utils in Docker)")
    return exe

def build_tex_for_question(stem_md: str, choices: dict) -> str:
    """Standalone doc that renders the question stem + (optional) choices."""
    # We purposely keep deps small: lmodern + amsmath + enumitem + array/booktabs if you need tables
    # Math is expected in TeX ($...$, \[...\]) already.
    choices_block = ""
    if choices:
        lines = ["\\begin{enumerate}[label=(\\Alph*)]"]
        for key in sorted(choices.keys()):
            lines.append(f"\\item {choices[key]}")
        lines.append("\\end{enumerate}")
        choices_block = "\n".join(lines)

    # Use 'standalone' for tight bounding box; fallback to article if you prefer.
    return textwrap.dedent(rf"""
    \documentclass[border=6pt,varwidth=0.95\linewidth]{standalone}
    \usepackage[T1]{{fontenc}}
    \usepackage[utf8]{{inputenc}}
    \usepackage{{lmodern}}
    \usepackage{{amsmath,amssymb}}
    \usepackage{{enumitem}}
    \usepackage{{array,booktabs}}
    \begin{document}
    \begin{{minipage}}{{0.95\linewidth}}
    {stem_md}

    {choices_block}
    \end{{minipage}}
    \end{document}
    """).strip()

def compile_to_svg(tex_source: str, dest_dir: str, base_name: str) -> str:
    """
    Compile tex_source to PDF via Tectonic, then to SVG via pdftocairo.
    Returns absolute path to SVG.
    """
    os.makedirs(dest_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tex_path = os.path.join(td, "doc.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        # 1) PDF via Tectonic
        cmd_pdf = [_tectonic(), "-q", "--outdir", td, tex_path]
        subprocess.run(cmd_pdf, check=True, cwd=td)

        pdf_path = os.path.join(td, "doc.pdf")
        if not os.path.exists(pdf_path):
            raise RuntimeError("Tectonic did not produce doc.pdf")

        # 2) SVG via pdftocairo
        svg_out = os.path.join(dest_dir, f"{base_name}.svg")
        cmd_svg = [_pdftocairo(), "-svg", pdf_path, svg_out]
        subprocess.run(cmd_svg, check=True)

        if not os.path.exists(svg_out):
            raise RuntimeError("pdftocairo did not produce SVG")
        return svg_out
    
def compile_tex(tex_source: str, timeout: int = 60) -> bytes:
    """
    Compile a LaTeX string to PDF bytes using the system 'tectonic' binary.
    Relies on existing helper '_tectonic()' to find the binary.
    Raises FileNotFoundError, subprocess.TimeoutExpired, or CalledProcessError.
    """
    tectonic = _tectonic()  # your existing helper; should raise if not found
    with tempfile.TemporaryDirectory() as tmpd:
        tex_path = os.path.join(tmpd, "doc.tex")
        pdf_path = os.path.join(tmpd, "doc.pdf")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        proc = subprocess.run(
            [tectonic, "--keep-logs", "--synctex", "--outdir", tmpd, tex_path],
            capture_output=True, text=True, timeout=timeout
        )
        if proc.returncode != 0:
            log.error("LaTeX compile failed rc=%s\nSTDERR:\n%s", proc.returncode, proc.stderr)
            raise subprocess.CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)

        with open(pdf_path, "rb") as f:
            return f.read()
