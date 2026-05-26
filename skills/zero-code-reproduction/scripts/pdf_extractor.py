#!/usr/bin/env python3
"""
pdf_extractor.py — 论文PDF文本提取 + 章节分割 + 公式定位

通用解析引擎的基础脚本。支持三种模式：
  extract   — 提取全文文本(按页)
  sections  — 智能章节分割
  locate    — 定位公式/表格/图所在页(供vision通道使用)
  pages     — 导出指定页为PNG图片(供vision分析)

运行环境: 需要venv python (PyMuPDF/fitz)
  VENV_PY="/home/lenovo/.hermes/hermes-agent/venv/bin/python3"
"""

import sys
import os
import json
import re
import fitz


# ============================================================
# 章节标题模式
# ============================================================
SECTION_PATTERNS = [
    # ── Standard IMRaD format: "1. Introduction", "2 Methods", "III. Results" ──
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Abstract)\s*$', 'abstract'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Introduction)\s*$', 'introduction'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Related\s+Work)\s*$', 'related_work'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Background)\s*$', 'background'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Method(?:s|ology)?)\s*$', 'methods'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Experimental?\s*(?:Setup|Design|Details)?)\s*$', 'methods'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Approach|Framework|Model|Architecture)\s*$', 'methods'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Results?(?:\s+and\s+Discussion)?)\s*$', 'results'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Experiments?(?:\s+and\s+Results)?)\s*$', 'results'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Evaluation)\s*$', 'results'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Discussion)\s*$', 'discussion'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Conclusion(?:s)?)\s*$', 'conclusion'),
    (r'^\s*(?:\d+\.?\s+|[IVX]+\.?\s+)?(Supplementary|Appendix|Supporting\s+Information)\s*$', 'supplementary'),
    (r'^\s*(References|Bibliography)\s*$', 'references'),
    # ── Science/Nature/Cell high-impact journal non-standard formats ──
    # Page-level headers (standalone lines)
    (r'^\s*RESEARCH\s+ARTICLE\s+SUMMARY\s*$', 'abstract'),
    (r'^\s*(?:STRUCTURED\s+)?ABSTRACT\s*$', 'abstract'),
    (r'^\s*MATERIALS?\s+AND\s+METHODS?\s*$', 'methods'),
    (r'^\s*(?:Materials?\s+and\s+methods?|STAR\s+Methods)\s*$', 'methods'),
    (r'^\s*(?:Supplementary|SUPPLEMENTARY)\s+(?:Materials?|Information|Text)\s*', 'supplementary'),
    # Inline section headers — "INTRODUCTION: text..." / "RATIONALE: text..."
    # These appear as ALL-CAPS label followed by colon at line start (Science format)
    (r'^\s*INTRODUCTION\s*:', 'introduction'),
    (r'^\s*RATIONALE\s*:', 'introduction'),
    (r'^\s*RESULTS?\s*:', 'results'),
    (r'^\s*METHODS?\s*:', 'methods'),
    (r'^\s*DISCUSSION\s*:', 'discussion'),
    (r'^\s*CONCLUSIONS?\s*:', 'conclusion'),
    # Nature "Methods" variants
    (r'^\s*Online\s+Methods?\s*$', 'methods'),
    (r'^\s*Methods?\s*$', 'methods'),
    (r'^\s*Data\s+availability\s*$', 'data_availability'),
    (r'^\s*Code\s+availability\s*$', 'code_availability'),
]

# 公式/表格/图定位关键词
FORMULA_SIGNALS = [
    r'(?:Eq(?:uation)?\.?\s*\(?\d+\)?)',    # Eq. (1), Equation 3
    r'(?:(?:^|\s)[\(\[]?\d+[\)\]]\s*$)',     # standalone equation numbers
    r'(?:=\s*\S+\s*[+\-×·]\s*\S+)',         # math expressions with operators
    r'(?:\\(?:sum|prod|int|frac|sqrt|alpha|beta|gamma|theta|lambda|sigma|nabla)\b)',
    r'(?:argmin|argmax|softmax|sigmoid|tanh)',
    r'(?:∑|∏|∫|√|α|β|γ|θ|λ|σ|∇|∈|∀|∃)',
    r'(?:mathcal|mathrm|mathbb|mathbf)',
]

TABLE_SIGNALS = [
    r'Table\s+\d+',
    r'TABLE\s+[IVX\d]+',
]

FIGURE_SIGNALS = [
    r'Fig(?:ure)?\.?\s*\d+',
    r'FIGURE\s+\d+',
]


# ============================================================
# 核心提取函数
# ============================================================
def extract_full_text(pdf_path):
    """提取PDF全文,按页返回。自动清理控制字符以确保JSON安全。"""
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text()
        # Clean control characters that break JSON serialization
        # Keep \n \r \t but remove \x00-\x08 \x0b \x0c \x0e-\x1f
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)
        pages.append({
            "page_num": i + 1,
            "char_count": len(text),
            "text": text
        })
    meta = {
        "total_pages": len(doc),
        "total_chars": sum(p["char_count"] for p in pages),
        "file": os.path.basename(pdf_path)
    }
    doc.close()
    return meta, pages


def split_sections(pages):
    """智能章节分割"""
    all_text = '\n'.join(p["text"] for p in pages)
    lines = all_text.split('\n')

    sections = {}
    current_section = "preamble"
    current_lines = []

    for line in lines:
        stripped = line.strip()
        matched = False
        for pattern, section_name in SECTION_PATTERNS:
            if re.match(pattern, stripped, re.IGNORECASE):
                # Save current section
                if current_lines:
                    text = '\n'.join(current_lines).strip()
                    if text:
                        if current_section in sections:
                            sections[current_section] += '\n\n' + text
                        else:
                            sections[current_section] = text
                current_section = section_name
                current_lines = []
                matched = True
                break
        if not matched:
            current_lines.append(line)

    # Save last section
    if current_lines:
        text = '\n'.join(current_lines).strip()
        if text:
            if current_section in sections:
                sections[current_section] += '\n\n' + text
            else:
                sections[current_section] = text

    return sections


def locate_elements(pages):
    """定位公式、表格、图所在的页码"""
    formula_pages = set()
    table_pages = set()
    figure_pages = set()
    formula_density = {}  # page → count of formula signals

    for p in pages:
        pnum = p["page_num"]
        text = p["text"]
        lines = text.split('\n')

        f_count = 0
        for line in lines:
            for pat in FORMULA_SIGNALS:
                if re.search(pat, line):
                    formula_pages.add(pnum)
                    f_count += 1
                    break

            for pat in TABLE_SIGNALS:
                if re.search(pat, line, re.IGNORECASE):
                    table_pages.add(pnum)
                    break

            for pat in FIGURE_SIGNALS:
                if re.search(pat, line, re.IGNORECASE):
                    figure_pages.add(pnum)
                    break

        if f_count > 0:
            formula_density[pnum] = f_count

    # Find formula-dense pages (top candidates for vision extraction)
    dense_threshold = 3
    vision_priority_pages = sorted(
        [p for p, c in formula_density.items() if c >= dense_threshold],
        key=lambda p: formula_density[p],
        reverse=True
    )

    return {
        "formula_pages": sorted(formula_pages),
        "table_pages": sorted(table_pages),
        "figure_pages": sorted(figure_pages),
        "vision_priority_pages": vision_priority_pages,
        "formula_density": formula_density
    }


def export_pages_as_images(pdf_path, page_numbers, output_dir, dpi=200):
    """将指定页导出为PNG图片(供vision模型分析)"""
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    exported = []

    for pnum in page_numbers:
        if pnum < 1 or pnum > len(doc):
            continue
        page = doc[pnum - 1]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img_path = os.path.join(output_dir, f"page_{pnum:03d}.png")
        pix.save(img_path)
        exported.append({"page_num": pnum, "path": img_path})

    doc.close()
    return exported


# ============================================================
# CLI
# ============================================================
def cmd_extract(pdf_path, max_pages=None):
    """提取全文文本"""
    meta, pages = extract_full_text(pdf_path)
    if max_pages:
        pages = pages[:int(max_pages)]
        meta["note"] = f"Truncated to first {max_pages} pages"

    output = {
        "meta": meta,
        "pages": [{"page_num": p["page_num"], "text": p["text"]} for p in pages]
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_sections(pdf_path):
    """章节分割"""
    meta, pages = extract_full_text(pdf_path)
    sections = split_sections(pages)

    output = {"meta": meta, "sections": {}}
    for name, text in sections.items():
        output["sections"][name] = {
            "char_count": len(text),
            "preview": text[:200] + "..." if len(text) > 200 else text
        }

    # Also output full sections for LLM consumption
    output["full_sections"] = sections
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_locate(pdf_path):
    """定位公式/表格/图"""
    meta, pages = extract_full_text(pdf_path)
    elements = locate_elements(pages)

    output = {
        "meta": meta,
        "elements": elements,
        "recommendations": {
            "vision_pages": elements["vision_priority_pages"][:5],
            "reason": "These pages have the highest density of mathematical formulas. "
                      "Use vision_analyze on exported PNG images for accurate formula extraction."
        }
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_pages(pdf_path, page_spec, output_dir="/tmp/paper_pages"):
    """导出指定页为PNG

    page_spec格式: "1,3,5" 或 "1-5" 或 "all"
    """
    meta, pages = extract_full_text(pdf_path)
    total = meta["total_pages"]

    if page_spec == "all":
        page_numbers = list(range(1, total + 1))
    elif '-' in page_spec:
        start, end = page_spec.split('-')
        page_numbers = list(range(int(start), int(end) + 1))
    else:
        page_numbers = [int(x.strip()) for x in page_spec.split(',')]

    exported = export_pages_as_images(pdf_path, page_numbers, output_dir)

    output = {
        "meta": meta,
        "exported": exported,
        "output_dir": output_dir
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_summary(pdf_path):
    """快速摘要：元信息 + 章节 + 元素定位 (供路由使用)"""
    meta, pages = extract_full_text(pdf_path)
    sections = split_sections(pages)
    elements = locate_elements(pages)

    # Extract title from first page (heuristic: first non-empty long line)
    title = "Unknown"
    if pages:
        for line in pages[0]["text"].split('\n'):
            stripped = line.strip()
            if len(stripped) > 20 and not stripped.startswith('http'):
                title = stripped
                break

    output = {
        "meta": {**meta, "title_guess": title},
        "section_sizes": {k: len(v) for k, v in sections.items()},
        "elements_summary": {
            "formula_page_count": len(elements["formula_pages"]),
            "table_page_count": len(elements["table_pages"]),
            "figure_page_count": len(elements["figure_pages"]),
            "vision_priority_pages": elements["vision_priority_pages"][:5]
        },
        "router_input": sections.get("abstract", sections.get("preamble", ""))[:3000],
        "methods_preview": (sections.get("methods", ""))[:3000]
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    usage = """Usage:
  python pdf_extractor.py extract <pdf_path> [max_pages]     — Full text extraction
  python pdf_extractor.py sections <pdf_path>                — Section splitting
  python pdf_extractor.py locate <pdf_path>                  — Locate formulas/tables/figures
  python pdf_extractor.py pages <pdf_path> <page_spec> [dir] — Export pages as PNG
  python pdf_extractor.py summary <pdf_path>                 — Quick summary for routing
"""
    if len(sys.argv) < 3:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    pdf = sys.argv[2]

    if cmd == 'extract':
        max_p = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_extract(pdf, max_p)
    elif cmd == 'sections':
        cmd_sections(pdf)
    elif cmd == 'locate':
        cmd_locate(pdf)
    elif cmd == 'pages':
        spec = sys.argv[3] if len(sys.argv) > 3 else "all"
        outdir = sys.argv[4] if len(sys.argv) > 4 else "/tmp/paper_pages"
        cmd_pages(pdf, spec, outdir)
    elif cmd == 'summary':
        cmd_summary(pdf)
    else:
        print(f"Unknown command: {cmd}")
        print(usage)
        sys.exit(1)
