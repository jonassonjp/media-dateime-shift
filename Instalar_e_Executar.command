#!/usr/bin/env bash
#
# Instalar_e_Executar.command
#
# Dê DUPLO-CLIQUE neste arquivo no Finder.
# Ele instala tudo o que falta (na primeira vez) e já abre o programa
# em seguida — não é preciso digitar nenhum comando no Terminal.
#
# Se o Finder recusar abrir na primeira vez ("desenvolvedor não
# identificado"), clique com o botão direito (ou Control+clique) sobre
# este arquivo, escolha "Abrir" e confirme — é uma proteção padrão do
# macOS para arquivos baixados da internet, só aparece uma vez.

# Garante que tudo roda a partir da pasta onde este arquivo está,
# não importa de onde foi clicado.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo "==========================================="
echo "   Media DateTime Shift — Setup e Execução"
echo "==========================================="
echo ""

pause_and_exit() {
    echo ""
    read -p "Pressione ENTER para fechar esta janela..." _
    exit 1
}

# 1. Python 3 -----------------------------------------------------------
if ! command -v python3 &> /dev/null; then
    echo "ERRO: Python 3 não encontrado neste Mac."
    echo "Instale em https://www.python.org/downloads/ e dê duplo-clique aqui de novo."
    pause_and_exit
fi
echo "✓ Python 3: $(python3 --version)"

# 2. exiftool -------------------------------------------------------------
if ! command -v exiftool &> /dev/null; then
    echo ""
    echo "exiftool não encontrado. Tentando instalar via Homebrew..."
    if ! command -v brew &> /dev/null; then
        echo ""
        echo "ERRO: Homebrew não encontrado neste Mac."
        echo "Instale primeiro em https://brew.sh e dê duplo-clique aqui de novo."
        pause_and_exit
    fi
    if ! brew install exiftool; then
        echo "ERRO ao instalar o exiftool pelo Homebrew."
        pause_and_exit
    fi
else
    echo "✓ exiftool: $(exiftool -ver)"
fi

# 3. Xcode Command Line Tools (SetFile, opcional) --------------------------
if ! command -v SetFile &> /dev/null; then
    echo ""
    echo "Aviso: 'SetFile' não encontrado (Xcode Command Line Tools)."
    echo "A data de CRIAÇÃO no Finder não será ajustada (só a de modificação)."
    echo "Para habilitar no futuro, abra o Terminal uma vez e rode:"
    echo "  xcode-select --install"
fi

# 4. Ambiente virtual -------------------------------------------------------
if [ ! -d "venv" ]; then
    echo ""
    echo "Criando ambiente virtual (só acontece na primeira vez)..."
    if ! python3 -m venv venv; then
        echo "ERRO ao criar o ambiente virtual."
        pause_and_exit
    fi
fi

echo ""
echo "Instalando/atualizando dependências..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo ""
echo "Tudo pronto! Iniciando o programa..."
echo ""

python3 src/media_datetime_shift.py
EXIT_CODE=$?

deactivate

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "Programa encerrado normalmente."
else
    echo "Programa encerrado (código $EXIT_CODE)."
fi
read -p "Pressione ENTER para fechar esta janela..." _
