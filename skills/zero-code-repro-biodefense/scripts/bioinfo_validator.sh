#!/bin/bash
# =============================================================================
# bioinfo_validator.sh — 检查复现所需的生物信息学工具是否已安装
#
# 用法: bash bioinfo_validator.sh [paper_tools.json]
#
# 不带参数时检查全部常用工具; 带参数时只检查指定工具。
# =============================================================================

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check_tool() {
    local name="$1"
    local cmd="$2"
    local required_version="${3:-}"

    printf "  %-25s" "$name"

    if command -v "$cmd" &>/dev/null; then
        # Try to get version
        local version=""
        version=$($cmd --version 2>&1 | head -1) || version="(version unknown)"

        if [ -n "$required_version" ]; then
            if echo "$version" | grep -q "$required_version"; then
                echo -e "${GREEN}✅ OK${NC} — $version"
                PASS=$((PASS + 1))
            else
                echo -e "${YELLOW}⚠️  INSTALLED${NC} but version mismatch (need $required_version): $version"
                WARN=$((WARN + 1))
            fi
        else
            echo -e "${GREEN}✅ OK${NC} — $version"
            PASS=$((PASS + 1))
        fi
    else
        echo -e "${RED}❌ MISSING${NC}"
        FAIL=$((FAIL + 1))
    fi
}

check_python_package() {
    local name="$1"
    local import_name="${2:-$1}"

    printf "  %-25s" "python:$name"

    if python3 -c "import $import_name; print($import_name.__version__)" 2>/dev/null; then
        echo -e " ${GREEN}✅${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "${RED}❌ MISSING${NC} (pip install $name)"
        FAIL=$((FAIL + 1))
    fi
}

echo "============================================================"
echo "  Bioinformatics Tool Availability Check"
echo "============================================================"
echo ""

echo "--- Core ML / Python packages ---"
check_python_package "torch" "torch"
check_python_package "transformers" "transformers"
check_python_package "peft" "peft"
check_python_package "scikit-learn" "sklearn"
check_python_package "pandas" "pandas"
check_python_package "numpy" "numpy"
check_python_package "networkx" "networkx"
check_python_package "biopython" "Bio"
check_python_package "pyyaml" "yaml"
echo ""

echo "--- Bioinformatics CLI tools ---"
check_tool "MMseqs2"        "mmseqs"         ""
check_tool "DefenseFinder"  "defense-finder"  ""
check_tool "PadLoc"         "padloc"          ""
check_tool "Prokka"         "prokka"          ""
check_tool "PanACoTA"       "panacota"        ""
check_tool "HMMER"          "hmmsearch"       ""
check_tool "MAFFT"          "mafft"           ""
check_tool "IQ-TREE"        "iqtree2"         ""
check_tool "MUSCLE"         "muscle"          ""
echo ""

echo "--- Optional tools ---"
check_tool "CD-HIT"         "cd-hit"          ""
check_tool "Diamond"        "diamond"         ""
check_tool "Samtools"       "samtools"        ""
echo ""

echo "============================================================"
echo -e "  Results: ${GREEN}${PASS} OK${NC}, ${YELLOW}${WARN} warnings${NC}, ${RED}${FAIL} missing${NC}"
echo "============================================================"

if [ $FAIL -gt 0 ]; then
    echo ""
    echo "To install missing tools:"
    echo "  Python packages:  pip install torch transformers peft scikit-learn pandas biopython networkx pyyaml"
    echo "  MMseqs2:          conda install -c bioconda mmseqs2"
    echo "  DefenseFinder:    pip install mdmparis-defense-finder && defense-finder update"
    echo "  PadLoc:           conda install -c padlocbio padloc && padloc --db-update"
    echo "  Prokka:           conda install -c bioconda prokka"
    echo "  PanACoTA:         pip install panacota"
    echo "  HMMER:            conda install -c bioconda hmmer"
    exit 1
else
    echo ""
    echo "All required tools are available!"
    exit 0
fi
