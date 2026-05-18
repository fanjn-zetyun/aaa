#!/usr/bin/env bash

set -euo pipefail

SRC_DIR="$1"
TGT_DIR="$2"

# 去掉末尾斜杠（避免路径问题）
SRC_DIR="${SRC_DIR%/}"
TGT_DIR="${TGT_DIR%/}"

# 检查目录是否存在
if [[ ! -d "$SRC_DIR" ]]; then
  echo "Source directory does not exist: $SRC_DIR"
  exit 1
fi

mkdir -p "$TGT_DIR"

# 遍历一级子目录
find "$SRC_DIR" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r subdir; do
    name="$(basename "$subdir")"
    link_path="$TGT_DIR/$name"

    if [[ -e "$link_path" ]]; then
        echo "Skip (already exists): $link_path"
        continue
    fi

    ln -s "$subdir" "$link_path"
    echo "Linked: $link_path -> $subdir"
done