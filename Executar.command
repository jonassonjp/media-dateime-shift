#!/usr/bin/env bash
#
# Executar.command
#
# Dê DUPLO-CLIQUE neste arquivo para apenas ABRIR o programa, já
# considerando que a instalação (Instalar_e_Executar.command) já foi
# feita antes. É a forma mais rápida para o uso do dia a dia.
#
# Se ainda não instalou nada neste Mac, dê duplo-clique primeiro em
# "Instalar_e_Executar.command" (só precisa ser feito uma vez).

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

clear
echo "==========================================="
echo "   Media DateTime Shift"
echo "==========================================="
echo ""

if [ ! -d "venv" ]; then
    echo "Ainda não encontrei a instalação (pasta 'venv' não existe)."
    echo ""
    echo "Dê duplo-clique em 'Instalar_e_Executar.command' primeiro"
    echo "(só precisa fazer isso uma vez)."
    echo ""
    read -p "Pressione ENTER para fechar esta janela..." _
    exit 1
fi

source venv/bin/activate
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
