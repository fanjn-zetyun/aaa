import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent


def _load_show_image():
    spec = importlib.util.spec_from_file_location("lab4ai_show_image", _SCRIPTS / "show_image.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_show = _load_show_image()
load_env_file = _show.load_env_file
show_images = _show.show_images


def _version_tuple(s: str) -> tuple[int, ...]:
    parts = []
    for p in re.split(r"[^\d]+", s.strip()):
        if p.isdigit():
            parts.append(int(p))
    return tuple(parts) if parts else ()


def _parse_torch_in_tag(tag: str) -> tuple[int, ...] | None:
    m = re.search(r"torch(\d+)\.(\d+)(?:\.(\d+))?", tag, re.I)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _parse_cuda_in_tag(tag: str) -> tuple[int, ...] | None:
    m = re.search(r"-cu(\d+)(?:\.(\d+))?(?:-\d+)?(?:\s|$)", tag, re.I)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) else 0
    return (major, minor)


def _parse_tf_in_tag(tag: str) -> tuple[int, ...] | None:
    m = re.search(r"-tf(\d+)\.(\d+)(?:\.(\d+))?", tag, re.I)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _parse_lf_in_tag(tag: str) -> tuple[int, ...] | None:
    m = re.search(r"lf(\d+)\.(\d+)(?:\.(\d+))?", tag, re.I)
    if not m:
        return None
    return tuple(int(x) for x in m.groups() if x is not None)


def _find_readme(project_dir: Path) -> tuple[Path | None, str]:
    for name in ("README.md", "readme.md", "Readme.md", "README.MD"):
        p = project_dir / name
        if p.is_file():
            try:
                return p, p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return p, ""
    return None, ""


def _read_extra_dep_files(project_dir: Path) -> str:
    chunks: list[str] = []
    for rel in ("environment.yml", "environment.yaml", "conda.yml", "requirements.txt", "pyproject.toml"):
        p = project_dir / rel
        if p.is_file():
            try:
                chunks.append(p.read_text(encoding="utf-8", errors="replace")[:8000])
            except OSError:
                pass
    return "\n".join(chunks)


def extract_hints(project_dir: Path, readme_text: str) -> dict[str, Any]:
    """
    Heuristic extraction of framework / CUDA hints from README and common dep files.
    Values are version tuples for scoring; None means unknown.
    """
    blob = (readme_text or "") + "\n" + _read_extra_dep_files(project_dir)
    low = blob.lower()

    torch_candidates: list[tuple[int, ...]] = []
    for pat in (
        r"torch\s*[=><~^!]+\s*v?(\d+\.\d+(?:\.\d+)?)",
        r"pytorch\s*[=><~^!]+\s*v?(\d+\.\d+(?:\.\d+)?)",
        r"torch==\s*(\d+\.\d+(?:\.\d+)?)",
        r"pytorch==\s*(\d+\.\d+(?:\.\d+)?)",
        r"torch\s*(\d+\.\d+(?:\.\d+)?)",
    ):
        for m in re.finditer(pat, low, re.I):
            t = _version_tuple(m.group(1))
            if t:
                torch_candidates.append(t)

    cuda_candidates: list[tuple[int, ...]] = []
    for pat in (
        r"cuda\s*(?:toolkit|version)?\s*[:=]?\s*(\d+)\.(\d+)",
        r"cuda\s+(\d+)\.(\d+)",
        r"\bcu(\d{2})(\d{2})\b",
        r"\bcu(\d+)\.(\d+)\b",
        r"cudatoolkit\s*[=><]+\s*(\d+)\.(\d+)",
    ):
        for m in re.finditer(pat, low, re.I):
            if len(m.groups()) == 2 and m.group(2).isdigit():
                cuda_candidates.append((int(m.group(1)), int(m.group(2))))
            elif m.lastindex == 1:
                t = _version_tuple(m.group(1))
                if len(t) >= 2:
                    cuda_candidates.append((t[0], t[1]))
                elif len(t) == 1:
                    cuda_candidates.append((t[0], 0))

    tf_candidates: list[tuple[int, ...]] = []
    for pat in (
        r"tensorflow\s*[=><~^!]+\s*v?(\d+\.\d+(?:\.\d+)?)",
        r"tf-?gpu\s*[=><~^!]+\s*v?(\d+\.\d+(?:\.\d+)?)",
    ):
        for m in re.finditer(pat, low, re.I):
            t = _version_tuple(m.group(1))
            if t:
                tf_candidates.append(t)

    wants_gpu = bool(
        re.search(r"\bgpu\b|\bcuda\b|\bcu\d|pytorch\+cu|torch\.cuda|nvidia", low)
    )

    def _best(cands: list[tuple[int, ...]]) -> tuple[int, ...] | None:
        if not cands:
            return None
        return max(cands, key=lambda t: (len(t), t))

    return {
        "torch": _best(torch_candidates),
        "cuda": _best(cuda_candidates),
        "tensorflow": _best(tf_candidates),
        "wants_gpu": wants_gpu,
    }


def _score_tag(tag: str, hints: dict[str, Any]) -> tuple[int, tuple[int, ...]]:
    """Return (score, tiebreaker) where higher is better."""
    t_torch = _parse_torch_in_tag(tag)
    t_cuda = _parse_cuda_in_tag(tag)
    t_tf = _parse_tf_in_tag(tag)
    t_lf = _parse_lf_in_tag(tag) or (0, 0, 0)

    score = 0
    want_torch = hints.get("torch")
    if want_torch:
        if t_torch == want_torch:
            score += 220
        elif t_torch and len(want_torch) >= 2 and t_torch[:2] == want_torch[:2]:
            score += 140
        elif t_torch and want_torch and t_torch[0] == want_torch[0]:
            score += 70

    want_cuda = hints.get("cuda")
    if want_cuda:
        if t_cuda == want_cuda:
            score += 180
        elif t_cuda and want_cuda and t_cuda[0] == want_cuda[0]:
            score += 95
        elif t_cuda and want_cuda and abs(t_cuda[0] * 100 + t_cuda[1] - (want_cuda[0] * 100 + want_cuda[1])) <= 2:
            score += 50

    want_tf = hints.get("tensorflow")
    if want_tf:
        if t_tf == want_tf:
            score += 100
        elif t_tf and len(want_tf) >= 2 and t_tf[:2] == want_tf[:2]:
            score += 60

    if hints.get("wants_gpu") and t_cuda:
        score += 15

    tb_torch = t_torch or (0, 0, 0)
    tb_cuda = t_cuda or (0, 0)
    tie_flat = tuple(t_lf) + tuple(tb_torch) + tuple(tb_cuda)
    return score, tie_flat


def _rank_tags(tags: list[str], hints: dict[str, Any]) -> list[str]:
    scored = []
    for t in tags:
        s, tb = _score_tag(t, hints)
        scored.append((s, tb, t))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in scored]


def _prepare_project_dir(paras: dict) -> tuple[str | None, Path | None]:
    """
    Returns (error_message, project_path) — project_path is real path to repo root.
    """
    root = paras.get("project_root") or paras.get("path") or paras.get("local_path")
    git_url = paras.get("git_url") or paras.get("repo_url")

    if bool(root) == bool(git_url):
        return "provide exactly one of project_root (or path) or git_url", None

    if root:
        p = Path(os.path.expanduser(str(root))).resolve()
        if not p.is_dir():
            return f"project_root not a directory: {p}", None
        return None, p

    url = str(git_url).strip()
    if not url:
        return "empty git_url", None

    branch = (paras.get("git_branch") or paras.get("branch") or "").strip()
    tmp = Path(tempfile.mkdtemp(prefix="lab4ai_image_choose_"))
    try:
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([url, str(tmp)])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            shutil.rmtree(tmp, ignore_errors=True)
            return f"git clone failed: {r.stderr.strip() or r.stdout.strip()}", None
        return None, tmp
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return f"git clone error: {str(e)}", None


def choose_image(paras: dict) -> dict:
    """
    Pick a recommended imageTag from Lab4AI based on project README / dep files.

    paras:
      - project_root | path | local_path: local project directory, **or**
      - git_url | repo_url: clone URL (optional git_branch / branch)
      - phone, password: optional if env LAB4AI_PHONE / LAB4AI_PASSWORD set

    Returns:
      {"code": int, "message": str, "data": {...}}  — data empty dict on failure
    """
    err, proj = _prepare_project_dir(paras)
    if err:
        return {"code": -1, "message": err, "data": {}}

    assert proj is not None
    cleanup_dir: Path | None = None
    if paras.get("git_url") or paras.get("repo_url"):
        cleanup_dir = proj

    try:
        readme_path, readme_text = _find_readme(proj)
        hints = extract_hints(proj, readme_text)
        list_out = show_images(paras)
        if list_out.get("code") != 0:
            return {
                "code": list_out.get("code", -1),
                "message": list_out.get("message") or "images_list failed",
                "data": {},
            }

        tags = list_out.get("data") or []
        if not tags:
            return {"code": -1, "message": "empty image list from API", "data": {}}

        ranked = _rank_tags(tags, hints)
        best = ranked[0]
        alts = ranked[1 : 1 + int(paras.get("max_alternates", 5))]

        reason_parts: list[str] = []
        if hints.get("torch"):
            reason_parts.append(f"README/deps torch ~{'.'.join(str(x) for x in hints['torch'])}")
        if hints.get("cuda"):
            reason_parts.append(f"CUDA ~{hints['cuda'][0]}.{hints['cuda'][1]}")
        if hints.get("tensorflow"):
            reason_parts.append(f"TensorFlow ~{'.'.join(str(x) for x in hints['tensorflow'])}")
        if not reason_parts:
            reason_parts.append("no explicit torch/cuda/tf in README/deps; picked newest lf/torch ordering")

        data = {
            "imageTag": best,
            "alternates": alts,
            "readme_path": str(readme_path) if readme_path else "",
            "project_path": str(proj),
            "hints": {
                "torch": list(hints["torch"]) if hints.get("torch") else [],
                "cuda": list(hints["cuda"]) if hints.get("cuda") else [],
                "tensorflow": list(hints["tensorflow"]) if hints.get("tensorflow") else [],
                "wants_gpu": bool(hints.get("wants_gpu")),
            },
            "reason": "; ".join(reason_parts),
        }
        return {"code": 0, "message": "", "data": data}
    finally:
        if cleanup_dir and paras.get("keep_clone") is not True:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


if __name__ == "__main__":
    load_env_file()
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "code": -1,
                    "message": 'usage: python image_choose.py \'{"project_root":"/path"} or {"git_url":"..."}\'',
                    "data": {},
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)
    try:
        paras_arg = json.loads(sys.argv[1])
    except Exception as e:
        print(json.dumps({"code": -1, "message": f"invalid json: {str(e)}", "data": {}}, ensure_ascii=False))
        sys.exit(1)

    print(json.dumps(choose_image(paras_arg), ensure_ascii=False))
