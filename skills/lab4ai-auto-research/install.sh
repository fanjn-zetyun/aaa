#!/bin/sh
# lab4ai-auto-research 安装脚本（POSIX sh，可用 sh install.sh；风格对齐 lab4ai-auto-reproduct/install.sh）
# 将本技能目录软链到 OPENCLAW_SKILLS（默认 ~/.openclaw/skills）一级目录。
# vendor/ 下第三方 skill（claw-shell、file-system、ssh-essentials）同步软链到同一目标，与 lab4ai-auto-reproduct/vendor 一致。
# 若本目录的**父目录**下存在 lab4ai-instance-manage / lab4ai-image-manage，一并链接（与 SKILL 中 ../ 依赖一致）。

set -eu

# 使用 $0 解析路径，兼容 `sh install.sh`（[[ 仅 bash 支持，此处统一用 POSIX [）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SKILLS_DIR="${OPENCLAW_SKILLS:-${HOME}/.openclaw/skills}"
VENDOR_DIR="$SCRIPT_DIR/vendor"

echo "🔧 lab4ai-auto-research 安装脚本"
echo "   本技能目录: $SCRIPT_DIR"
echo "   仓库根（用于探测兄弟技能）: $REPO_ROOT"
echo "   OpenClaw skills 目标: $SKILLS_DIR"
echo ""

mkdir -p "$SKILLS_DIR"

link_one() {
  src="$1"
  name="$2"
  target="$SKILLS_DIR/$name"

  if [ ! -d "$src" ]; then
    echo "   (跳过) 无目录: $name — $src"
    return 0
  fi

  abs="$(cd "$src" && pwd)"

  if [ -L "$target" ]; then
    echo "🔄 更新软链接: $name"
    rm "$target"
  elif [ -e "$target" ]; then
    echo "⚠️  跳过 $name（目标已存在且非软链接: $target）"
    return 0
  else
    echo "✅ 创建软链接: $name"
  fi

  ln -sfn "$abs" "$target"
}

link_one "$SCRIPT_DIR" "lab4ai-auto-research"
link_one "$REPO_ROOT/lab4ai-instance-manage" "lab4ai-instance-manage"
link_one "$REPO_ROOT/lab4ai-image-manage" "lab4ai-image-manage"

if [ -d "$VENDOR_DIR" ]; then
  for skill_dir in "$VENDOR_DIR"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name=$(basename "$skill_dir")
    link_one "$skill_dir" "$skill_name"
  done
fi

echo ""
echo "✅ 安装完成。当前链接情况:"
for name in lab4ai-auto-research lab4ai-instance-manage lab4ai-image-manage; do
  t="$SKILLS_DIR/$name"
  if [ -L "$t" ]; then
    echo "   $name -> $(readlink "$t")"
  fi
done
if [ -d "$VENDOR_DIR" ]; then
  for skill_dir in "$VENDOR_DIR"/*/; do
    [ -d "$skill_dir" ] || continue
    skill_name=$(basename "$skill_dir")
    t="$SKILLS_DIR/$skill_name"
    if [ -L "$t" ]; then
      echo "   $skill_name -> $(readlink "$t")"
    fi
  done
fi
