import os, re, sys, json, tempfile, subprocess, shutil, zipfile
from pathlib import Path

USE_LATEX_SVG = False
LATEX_TEMPLATE = r"""
\documentclass[preview,12pt]{standalone}

%% --- Math packages ---
\usepackage{amsmath,amssymb,amsthm,mathtools}
\usepackage{bm}
\usepackage{physics}

%% --- Fonts & typography ---
\usepackage{newtxtext,newtxmath}
\usepackage{microtype}
\linespread{1.1}

%% --- Colors & styling ---
\usepackage{xcolor}
\definecolor{PandoraBlue}{HTML}{1E90FF}
\definecolor{PandoraGray}{HTML}{555555}
\definecolor{PandoraAccent}{HTML}{007ACC}

%% --- Boxes and emphasis ---
\usepackage[most]{tcolorbox}
\tcbset{
  enhanced,
  colframe=PandoraAccent!80!black,
  colback=PandoraAccent!5!white,
  boxrule=0.8pt,
  arc=2pt,
  outer arc=2pt,
  left=6pt,right=6pt,top=4pt,bottom=4pt
}

%% --- Headings ---
\usepackage{titlesec}
\titleformat{\section}{\large\bfseries\color{PandoraAccent}}{}{0em}{}
\titleformat{\subsection}{\normalsize\bfseries\color{PandoraBlue}}{}{0em}{}

%% --- Custom boxes ---
\newtcolorbox{definitionbox}{colback=PandoraAccent!5,colframe=PandoraAccent!60!black,title=\textbf{Definition}}
\newtcolorbox{examplebox}{colback=PandoraBlue!5,colframe=PandoraBlue!70!black,title=\textbf{Example}}
\newtcolorbox{questionbox}{colback=PandoraGray!5,colframe=PandoraGray!60!black,title=\textbf{Question}}
\newtcolorbox{answerbox}{colback=green!5!white,colframe=green!60!black,title=\textbf{Answer}}

%% --- Page layout ---
\setlength{\parskip}{4pt}
\setlength{\parindent}{0pt}

%% --- Symbols & utilities ---
\usepackage{siunitx}
\usepackage{cancel}
\usepackage{hyperref}
\hypersetup{colorlinks=true,linkcolor=PandoraAccent,urlcolor=PandoraAccent}

\begin{document}
%s
\end{document}
"""


def wrap_latex_snippet(snippet: str) -> str:
    """Wrap a LaTeX snippet in a minimal document so it can compile standalone."""
    return LATEX_TEMPLATE % snippet.strip()


def run_manim(code: str, outdir: Path, idx: int):
    """Render a single Manim scene in isolation (unique class + tempdir)."""
    class_name = f"PandoraScene_{idx}"
    indented_code = "\n".join("        " + l for l in code.strip().splitlines())
    scene_code = f"""from manim import *

class {class_name}(Scene):
    def construct(self):
        self.camera.background_color = "WHITE"
{indented_code}
"""
    scene_dir = outdir / f"scene_{idx}"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scene_path = scene_dir / f"scene_{idx}.py"
    scene_path.write_text(scene_code, encoding="utf-8")

    try:
        subprocess.run(
            [
                "manim", "render", str(scene_path), class_name,
                "-ql", "--disable_caching", "-o", f"scene_{idx}.mp4"
            ],
            check=True,
            cwd=scene_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for p in scene_dir.rglob("*.mp4"):
            return p
    except subprocess.CalledProcessError as e:
        print(f"[WARN] ❌ Manim render failed for snippet {idx}: {e}")
        print(e.stderr.decode(errors="ignore"))
    return None


def parse_latex(tex):
    # Only detect global layout once at the start, not inside snippets
    layout = "two-column" if re.search(r"(?m)^(?:%%\s*twocolumn|\\twocolumn|\\document\[.*twocolumn.*\])", tex) else "single-column"
    elements = []
    pos = 0

    # handle \begin{manim}...\end{manim}
    for m in re.finditer(r"\\begin\{manim\}([\s\S]*?)\\end\{manim\}", tex):
        before = tex[pos:m.start()].strip()
        if before:
            elements.append({"type": "latex", "text": before})
        elements.append({"type": "manim", "code": m.group(1).strip()})
        pos = m.end()
    after = tex[pos:].strip()
    if after:
        elements.append({"type": "latex", "text": after})

    expanded = []
    for el in elements:
        if el["type"] != "latex":
            expanded.append(el)
            continue

        t = el["text"]

        # Inline \manim{...}
        def repl_inline(m):
            expanded.append({"type": "manim", "code": m.group(1)})
            return ""
        t = re.sub(r"\\manim\{([^}]*)\}", repl_inline, t)

        # Page breaks
        parts = re.split(r"(\\newpage|\\breakpage)", t)
        for part in parts:
            if not part.strip():
                continue
            if part.strip() in ("\\newpage", "\\breakpage"):
                expanded.append({"type": "pagebreak"})
                continue

            # image/video [options]{path}
            def parse_media(match, typ):
                opt, path = match.groups()
                width = height = scale = None
                if opt:
                    width = re.search(r"width\s*=\s*([0-9]+%|[0-9]+px)", opt)
                    height = re.search(r"height\s*=\s*([0-9]+%|[0-9]+px)", opt)
                    scale = re.search(r"scale\s*=\s*([0-9.]+)", opt)
                return {
                    "type": typ,
                    "file": path.strip(),
                    "width": width.group(1) if width else None,
                    "height": height.group(1) if height else None,
                    "scale": scale.group(1) if scale else None,
                }

            for typ in ("image", "video"):
                for m in re.finditer(rf"\\{typ}\[?([^\]]*)\]?\{{([^}}]+)\}}", part):
                    expanded.append(parse_media(m, typ))
                    part = part.replace(m.group(0), "")
            if part.strip():
                expanded.append({"type": "latex", "text": part.strip()})
    return expanded, layout

import subprocess

def render_latex_to_svg(tex_code: str, outpath: Path):
    """Compile LaTeX code to SVG using pdflatex + dvisvgm."""
    workdir = outpath.parent
    texfile = workdir / "temp.tex"
    clean_code = re.sub(
    r"\\documentclass.*|\\usepackage.*|\\begin\{document\}|\\end\{document\}",
    "",
        tex_code
    )


    texfile.write_text(wrap_latex_snippet(clean_code), encoding="utf-8")

    # Step 1: Compile to DVI (faster, no PDF needed)
    subprocess.run(
        ["latex", "-interaction=nonstopmode", str(texfile)],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )

    # Step 2: Convert DVI -> SVG
    subprocess.run(
        ["dvisvgm", "temp.dvi", "-n", "-a", "-o", str(outpath)],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return outpath if outpath.exists() else None


def main():
    if len(sys.argv) < 3:
        print("Usage: python create2.py <input.tex> -o <output.pandora>")
        return
    infile = Path(sys.argv[1])
    outfile = Path(sys.argv[sys.argv.index("-o") + 1])

    tex = infile.read_text(encoding="utf-8")
    elements, layout = parse_latex(tex)
    print(f"[DEBUG] Found {len(elements)} document elements")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        sequence = []

        for i, el in enumerate(elements):
            if el["type"] == "pagebreak":
                sequence.append({"type": "pagebreak"})
                continue

            if el["type"] == "manim":
                print(f"[INFO] 🎬 Running manim for snippet {i}")
                vpath = run_manim(el["code"], tmpdir, i)
                if vpath and vpath.exists():
                    rel = f"videos/scene_{i}.mp4"
                    dest = tmpdir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(vpath, dest)
                    sequence.append({"type": "video", "file": rel})
                else:
                    sequence.append({"type": "error", "text": f"Manim render failed snippet {i}"})
                continue

            if el["type"] in ("video", "image"):
                rel = f"{el['type']}s/{Path(el['file']).name}"
                dest = tmpdir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if Path(el["file"]).exists():
                    shutil.copy(el["file"], dest)
                sequence.append({**el, "file": rel})
                continue

            if el["type"] == "latex":
                rel_svg = f"latex/block_{i}.svg"
                dest_svg = tmpdir / rel_svg
                dest_svg.parent.mkdir(parents=True, exist_ok=True)

                try:
                    render_latex_to_svg(el["text"], dest_svg)
                    sequence.append({"type": "latex", "file": rel_svg})
                except subprocess.CalledProcessError as e:
                    print(f"[WARN] ❌ LaTeX render failed for block {i}")
                    print(e.stderr.decode(errors='ignore'))
                    sequence.append({"type": "error", "text": f"LaTeX render failed for block {i}"})

        meta = {"layout": layout, "sequence": sequence}
        (tmpdir / "meta.json").write_text(json.dumps(meta, indent=2))

        with zipfile.ZipFile(outfile, "w", zipfile.ZIP_DEFLATED) as z:
            for p in tmpdir.rglob("*"):
                z.write(p, p.relative_to(tmpdir))
        print(f"[INFO] ✅ Built {len(sequence)} elements -> {outfile}")


if __name__ == "__main__":
    main()
