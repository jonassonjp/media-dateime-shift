#!/usr/bin/env bash
#
# install.sh — instala dependências e cria o ambiente virtual do
# Media DateTime Shift.
#
# Uso:
#   chmod +x install.sh
#   ./install.sh
#
set -e

echo "=== Instalação - Media DateTime Shift ==="
echo ""

# 1. Verifica Python 3 ------------------------------------------------------
if ! command -v python3 &> /dev/null; then
    echo "ERRO: Python 3 não encontrado."
    echo "Instale via https://www.python.org/downloads/ ou 'brew install python3'"
    exit 1
fi
echo "✓ Python 3 encontrado: $(python3 --version)"

# 2. Verifica/instala exiftool ----------------------------------------------
if ! command -v exiftool &> /dev/null; then
    echo "exiftool não encontrado no PATH."
    if command -v brew &> /dev/null; then
        echo "Instalando exiftool via Homebrew..."
        brew install exiftool
    else
        echo "ERRO: Homebrew não encontrado."
        echo "Instale o Homebrew (https://brew.sh) e depois rode:"
        echo "  brew install exiftool"
        exit 1
    fi
else
    echo "✓ exiftool encontrado: $(exiftool -ver)"
fi

# 3. Verifica Xcode Command Line Tools (SetFile, opcional) ------------------
if ! command -v SetFile &> /dev/null; then
    echo ""
    echo "Aviso: 'SetFile' não encontrado (Xcode Command Line Tools)."
    echo "Sem ele, a data de CRIAÇÃO do Finder não poderá ser ajustada"
    echo "(apenas a data de modificação)."
    echo "Para instalar, rode: xcode-select --install"
    echo ""
fi

# 4. Cria ambiente virtual ---------------------------------------------------
echo "Criando ambiente virtual em ./venv ..."
python3 -m venv venv

# 5. Instala dependências -----------------------------------------------------
echo "Instalando dependências Python..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
deactivate

echo ""
echo "✓ Instalação concluída!"
echo ""
echo "Para usar o programa:"
echo "  source venv/bin/activate"
echo "  python3 src/media_datetime_shift.py"
echo ""
echo "Para sair do ambiente virtual depois:"
echo "  deactivate"
