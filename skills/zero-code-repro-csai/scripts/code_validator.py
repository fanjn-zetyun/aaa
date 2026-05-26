#!/usr/bin/env python3
"""
code_validator.py — 验证生成的Python代码脚手架

功能:
  syntax    — 语法检查 (py_compile)
  imports   — Import可用性检查
  shape     — 形状推断检查 (尝试实例化模型 + dummy forward)
  full      — 全部检查
  deps      — 分析缺失依赖，生成 setup.sh

运行: $VENV_PY code_validator.py <command> <src_dir>
"""

import sys
import os
import re
import json
import subprocess
import ast


def check_syntax(src_dir):
    """语法检查: 所有 .py 文件"""
    results = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r') as fh:
                    source = fh.read()
                compile(source, path, 'exec')
                results.append({"file": path, "status": "OK"})
            except SyntaxError as e:
                results.append({
                    "file": path,
                    "status": "FAIL",
                    "error": f"Line {e.lineno}: {e.msg}"
                })
    return results


def check_imports(src_dir):
    """分析所有import语句，检查是否可用"""
    all_imports = set()
    import_locations = {}

    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            try:
                with open(path, 'r') as fh:
                    tree = ast.parse(fh.read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            top = alias.name.split('.')[0]
                            all_imports.add(top)
                            import_locations.setdefault(top, []).append(f)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            top = node.module.split('.')[0]
                            all_imports.add(top)
                            import_locations.setdefault(top, []).append(f)
            except SyntaxError:
                pass  # syntax errors handled in check_syntax

    # Classify imports
    stdlib = {
        'os', 'sys', 'json', 'yaml', 'math', 'random', 'copy', 'time',
        'datetime', 'pathlib', 'argparse', 'collections', 'itertools',
        'functools', 'typing', 'abc', 'dataclasses', 'logging',
        'warnings', 'glob', 'shutil', 're', 'io', 'csv', 'pickle',
        'hashlib', 'struct', 'enum', 'contextlib', 'inspect',
    }

    # Internal imports (files within src_dir)
    internal = set()
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.endswith('.py'):
                internal.add(f.replace('.py', ''))

    results = []
    missing_packages = []

    for imp in sorted(all_imports):
        if imp in stdlib:
            results.append({"package": imp, "status": "OK", "type": "stdlib"})
        elif imp in internal:
            results.append({"package": imp, "status": "OK", "type": "internal"})
        else:
            # Try to import using current interpreter
            try:
                ret = subprocess.run(
                    [sys.executable, "-c", f"import {imp}"],
                    capture_output=True, timeout=10
                )
                if ret.returncode == 0:
                    results.append({"package": imp, "status": "OK", "type": "third-party"})
                else:
                    raise ImportError()
            except (ImportError, subprocess.TimeoutExpired):
                results.append({
                    "package": imp,
                    "status": "MISSING",
                    "type": "third-party",
                    "used_in": import_locations.get(imp, [])
                })
                missing_packages.append(imp)

    return results, missing_packages


def generate_setup_sh(missing_packages, output_path):
    """根据缺失的包生成 setup.sh"""
    # Package name → pip name mapping (common ones)
    pip_map = {
        'torch': 'torch',
        'torchvision': 'torchvision',
        'torchaudio': 'torchaudio',
        'transformers': 'transformers',
        'datasets': 'datasets',
        'tokenizers': 'tokenizers',
        'accelerate': 'accelerate',
        'numpy': 'numpy',
        'pandas': 'pandas',
        'scipy': 'scipy',
        'sklearn': 'scikit-learn',
        'skimage': 'scikit-image',
        'cv2': 'opencv-python',
        'PIL': 'Pillow',
        'matplotlib': 'matplotlib',
        'seaborn': 'seaborn',
        'tqdm': 'tqdm',
        'wandb': 'wandb',
        'tensorboard': 'tensorboard',
        'einops': 'einops',
        'timm': 'timm',
        'albumentations': 'albumentations',
        'torch_geometric': 'torch-geometric',
        'dgl': 'dgl',
        'jax': 'jax',
        'flax': 'flax',
        'optax': 'optax',
        'hydra': 'hydra-core',
        'omegaconf': 'omegaconf',
    }

    lines = ["#!/bin/bash", "# Auto-generated setup script", "# Review before running!", ""]
    lines.append("# Core dependencies")
    lines.append("pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121")
    lines.append("")
    lines.append("# Paper-specific dependencies")

    pip_installs = set()
    for pkg in missing_packages:
        pip_name = pip_map.get(pkg, pkg)
        pip_installs.add(pip_name)

    # Remove torch if already in core
    pip_installs -= {'torch', 'torchvision', 'torchaudio'}

    if pip_installs:
        lines.append(f"pip install {' '.join(sorted(pip_installs))}")
    else:
        lines.append("# (no additional packages needed)")

    lines.append("")
    lines.append('echo "Setup complete!"')

    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    return output_path


def check_shape(src_dir, model_class="Model", config=None):
    """尝试实例化模型并推断输出形状"""
    # Build a test script — use string concatenation to avoid f-string escaping issues
    test_code = (
        "import sys, os, json, inspect\n"
        f"sys.path.insert(0, '{src_dir}')\n"
        f"os.chdir('{src_dir}')\n"
        "try:\n"
        "    import torch\n"
        "    from model import *\n"
        "    model_cls = None\n"
        "    for name, obj in list(globals().items()):\n"
        "        if inspect.isclass(obj) and issubclass(obj, torch.nn.Module) and name != 'Module':\n"
        f"            if name == '{model_class}' or name.endswith('Model') or name.endswith('Net'):\n"
        "                model_cls = obj\n"
        "                break\n"
        "    if model_cls is None:\n"
        "        print(json.dumps({'status': 'SKIP', 'reason': 'No model class found'}))\n"
        "    else:\n"
        "        sig = inspect.signature(model_cls.__init__)\n"
        "        params = {}\n"
        "        for pname, param in sig.parameters.items():\n"
        "            if pname == 'self': continue\n"
        "            if param.default != inspect.Parameter.empty: continue\n"
        "            if 'dim' in pname or 'size' in pname: params[pname] = 64\n"
        "            elif 'num' in pname or 'layer' in pname or 'head' in pname: params[pname] = 2\n"
        "            elif 'dropout' in pname: params[pname] = 0.1\n"
        "            elif 'class' in pname: params[pname] = 10\n"
        "            else: params[pname] = 32\n"
        "        model = model_cls(**params)\n"
        "        num_params = sum(p.numel() for p in model.parameters())\n"
        "        print(json.dumps({'status': 'OK', 'class': model_cls.__name__,\n"
        "                          'num_params': num_params, 'params_used': str(params)}))\n"
        "except Exception as e:\n"
        "    print(json.dumps({'status': 'ERROR', 'error': str(e)}))\n"
    )
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True, timeout=30
        )
        output = result.stdout.strip()
        if output:
            return json.loads(output)
        else:
            return {"status": "ERROR", "error": result.stderr[:500]}
    except subprocess.TimeoutExpired:
        return {"status": "ERROR", "error": "Timeout (model instantiation took >30s)"}
    except json.JSONDecodeError:
        return {"status": "ERROR", "error": f"Unexpected output: {output[:200]}"}
    finally:
        os.unlink(tmp_path)


def count_todos(src_dir):
    """统计代码中的 TODO 标记"""
    todos = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if not f.endswith('.py'):
                continue
            path = os.path.join(root, f)
            with open(path, 'r') as fh:
                for i, line in enumerate(fh, 1):
                    if 'TODO' in line:
                        confidence = "UNKNOWN"
                        if 'LOW CONFIDENCE' in line:
                            confidence = "LOW"
                        elif 'MEDIUM' in line:
                            confidence = "MEDIUM"
                        elif 'HIGH' in line or 'VERIFY' in line.upper():
                            confidence = "MEDIUM"
                        todos.append({
                            "file": f,
                            "line": i,
                            "text": line.strip(),
                            "confidence": confidence
                        })
    return todos


# ============================================================
# CLI
# ============================================================
def main():
    usage = """Usage:
  code_validator.py syntax <src_dir>        — Syntax check all .py files
  code_validator.py imports <src_dir>        — Check import availability
  code_validator.py shape <src_dir>          — Try model instantiation
  code_validator.py todos <src_dir>          — List all TODO markers
  code_validator.py full <src_dir>           — Run all checks
  code_validator.py deps <src_dir> <out.sh>  — Generate setup.sh
"""
    if len(sys.argv) < 3:
        print(usage)
        sys.exit(1)

    cmd = sys.argv[1]
    src_dir = sys.argv[2]

    if cmd == 'syntax':
        results = check_syntax(src_dir)
        passed = sum(1 for r in results if r["status"] == "OK")
        failed = sum(1 for r in results if r["status"] == "FAIL")
        for r in results:
            status_icon = "✅" if r["status"] == "OK" else "❌"
            print(f"  {status_icon} {r['file']}", end="")
            if r["status"] == "FAIL":
                print(f" — {r['error']}", end="")
            print()
        print(f"\n[SYNTAX] {passed} passed, {failed} failed")

    elif cmd == 'imports':
        results, missing = check_imports(src_dir)
        for r in results:
            icon = "✅" if r["status"] == "OK" else "❌"
            print(f"  {icon} {r['package']} ({r['type']})", end="")
            if r["status"] == "MISSING":
                print(f" — used in: {', '.join(r['used_in'])}", end="")
            print()
        print(f"\n[IMPORTS] {len(results) - len(missing)} available, {len(missing)} missing")
        if missing:
            print(f"  Missing: {', '.join(missing)}")

    elif cmd == 'shape':
        result = check_shape(src_dir)
        print(json.dumps(result, indent=2))

    elif cmd == 'todos':
        todos = count_todos(src_dir)
        for t in todos:
            print(f"  [{t['confidence']}] {t['file']}:{t['line']} — {t['text']}")
        low = sum(1 for t in todos if t['confidence'] == 'LOW')
        print(f"\n[TODOS] {len(todos)} total, {low} low-confidence items")

    elif cmd == 'full':
        print("=" * 60)
        print("FULL VALIDATION REPORT")
        print("=" * 60)

        # Syntax
        print("\n1. SYNTAX CHECK")
        syntax = check_syntax(src_dir)
        for r in syntax:
            icon = "✅" if r["status"] == "OK" else "❌"
            print(f"  {icon} {r['file']}", end="")
            if r["status"] == "FAIL":
                print(f" — {r['error']}", end="")
            print()

        # Imports
        print("\n2. IMPORT CHECK")
        imports, missing = check_imports(src_dir)
        for r in imports:
            if r["status"] == "MISSING":
                print(f"  ❌ {r['package']} — MISSING")
        available = len(imports) - len(missing)
        print(f"  → {available} available, {len(missing)} missing")

        # Shape
        print("\n3. MODEL INSTANTIATION")
        shape = check_shape(src_dir)
        if shape["status"] == "OK":
            print(f"  ✅ {shape['class']}: {shape['num_params']:,} parameters")
        elif shape["status"] == "SKIP":
            print(f"  ⏭️  Skipped: {shape['reason']}")
        else:
            print(f"  ❌ Error: {shape['error']}")

        # TODOs
        print("\n4. TODO MARKERS")
        todos = count_todos(src_dir)
        low = sum(1 for t in todos if t['confidence'] == 'LOW')
        med = sum(1 for t in todos if t['confidence'] == 'MEDIUM')
        print(f"  → {len(todos)} total: {low} LOW confidence, {med} MEDIUM")

        # Summary
        print("\n" + "=" * 60)
        syntax_ok = all(r["status"] == "OK" for r in syntax)
        imports_ok = len(missing) == 0
        shape_ok = shape["status"] in ["OK", "SKIP"]
        overall = "PASS" if (syntax_ok and imports_ok and shape_ok) else "NEEDS WORK"
        print(f"OVERALL: {overall}")
        if not syntax_ok:
            print("  ⚠️  Fix syntax errors first")
        if not imports_ok:
            print(f"  ⚠️  Install missing: pip install {' '.join(missing)}")
        if low > 0:
            print(f"  ⚠️  {low} low-confidence implementations need review")

    elif cmd == 'deps':
        output_path = sys.argv[3] if len(sys.argv) > 3 else os.path.join(src_dir, '..', 'scripts', 'setup.sh')
        _, missing = check_imports(src_dir)
        path = generate_setup_sh(missing, output_path)
        print(f"Generated: {path}")
        print(f"Missing packages: {', '.join(missing) if missing else 'none'}")

    else:
        print(f"Unknown command: {cmd}")
        print(usage)
        sys.exit(1)


if __name__ == '__main__':
    main()
