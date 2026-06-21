# Media DateTime Shift

Ferramenta de linha de comando, em Python, para corrigir a data/hora de
fotos e vídeos cujo relógio da câmera/celular estava com o **fuso horário
errado**. Ajusta tanto os **metadados internos** (EXIF/QuickTime) quanto as
**datas do arquivo no Finder** (macOS).

## Formatos suportados

| Categoria | Extensões |
|---|---|
| Fotos | `.jpg` `.jpeg` `.heic` `.heif` `.dng` `.tif` `.tiff` `.png` |
| RAW | `.cr2` `.cr3` `.nef` `.arw` `.orf` `.rw2` `.raf` `.raw` |
| Vídeos | `.mov` `.mp4` `.m4v` `.avi` `.3gp` `.mts` `.m2ts` |

## Pré-requisitos

- macOS com Python 3.9+
- [Homebrew](https://brew.sh)
- [exiftool](https://exiftool.org/) — instalado automaticamente pelo script de instalação via `brew install exiftool`
- (Opcional, recomendado) **Xcode Command Line Tools**, para que a data de
  **criação** do Finder também seja ajustada (não só a de modificação):
  ```
  xcode-select --install
  ```

## Instalação e uso (sem digitar comandos)

Há dois arquivos de duplo-clique na raiz do projeto:

| Arquivo | Quando usar |
|---|---|
| **`Instalar_e_Executar.command`** | Na **primeira vez** (faz toda a instalação) — ou sempre que quiser, ele detecta o que já está pronto e pula essas etapas. |
| **`Executar.command`** | No **dia a dia**, depois que já instalou uma vez — pula as checagens e abre o programa direto, mais rápido. |

### Primeira vez

1. Baixe e descompacte o `.zip` do projeto (duplo-clique no Finder já
   descompacta).
2. Dentro da pasta `media-datetime-shift`, dê **duplo-clique** em
   **`Instalar_e_Executar.command`**.

Esse arquivo:
1. Confere se Python 3 está instalado.
2. Instala o `exiftool` via Homebrew, se necessário.
3. Avisa se o `SetFile` (Xcode CLT) não está disponível.
4. Cria o ambiente virtual (`venv/`).
5. Instala/atualiza as dependências Python.
6. **Já abre o programa interativo**, na mesma janela do Terminal.

### Próximas vezes

Dê duplo-clique em **`Executar.command`** — ele pula direto para abrir
o programa, sem refazer as checagens de instalação. (Se a instalação
ainda não tiver sido feita, ele avisa e pede para rodar o
`Instalar_e_Executar.command` primeiro.)

> **Aviso do macOS na primeira vez:** o macOS pode recusar abrir com um
> aviso de "desenvolvedor não identificado" (proteção padrão para
> arquivos baixados da internet). Se isso acontecer, clique com o botão
> direito (ou Control+clique) sobre o arquivo `.command`, escolha
> **Abrir** e confirme. Só acontece uma vez por arquivo.

> Se o ícone não tiver a aparência de executável ou der erro de
> permissão, abra o Terminal **uma única vez** dentro da pasta do
> projeto e rode: `chmod +x Instalar_e_Executar.command Executar.command`.

### Alternativa via Terminal (linha de comando)

Se preferir o caminho manual:

```bash
chmod +x install.sh
./install.sh
source venv/bin/activate
python3 src/media_datetime_shift.py
```

`install.sh` faz os mesmos passos 1–5 acima, mas sem rodar o programa
ao final — útil para quem quer controlar a ativação do venv manualmente.

### O que o programa pergunta

Ao abrir, o programa mostra um menu:

```
=============================================
  Media DateTime Shift
  Corrige data/hora de fotos e vídeos
=============================================

O que deseja fazer?

  1 - Alterar DATA  (ajusta por dias, ex: +1, -3)
  2 - Alterar HORA  (ajusta por horas, ex: +3, -5)
  3 - Definir data/hora exata (digite o valor certo)
  0 - Sair

Escolha uma opção:
```

- **`1` (Alterar DATA)** — pergunta quantos **dias** ajustar (ex: `+1`,
  `-3`). Útil quando a data inteira está errada.
- **`2` (Alterar HORA)** — pergunta quantas **horas** ajustar (ex: `+3`,
  `-5`, `+27`). Funciona também para grandes deslocamentos (`+27`
  horas), que automaticamente avançam a data também ao passar da
  meia-noite.
- **`3` (Definir data/hora exata)** — em vez de você calcular a
  diferença de cabeça, digite a data/hora **certa** e o programa
  calcula o ajuste sozinho (veja detalhes abaixo).
- **`0` (Sair)** — encerra o programa.

Depois de escolher `1`, `2` ou `3`, o fluxo continua parecido:

1. **O que deseja processar?**
   - `[1]` Diretório inteiro — busca recursiva por todos os arquivos de
     mídia suportados dentro da pasta informada.
   - `[2]` Arquivos específicos — você informa um ou mais caminhos
     (separados por vírgula), com suporte a curingas, ex: `*.JPG`.

2. **Modo simulação?** Se responder `s`, o programa mostra o que faria
   sem alterar nada — útil para conferir antes de aplicar de verdade.

3. **Manter backups?** Por padrão (`S`), o programa copia o arquivo
   original para `arquivo.jpg_original` **antes** de alterar os
   metadados — sempre atualizando essa cópia a cada execução (mais
   detalhes abaixo). Recomendado manter ligado até confirmar que o
   resultado está correto.

4. **Confirmação final**, com um resumo da operação antes de aplicar.

Ao terminar, o programa volta para o menu principal — dá para fazer
quantas operações quiser (ex: ajustar a data de um lote e depois a hora
de outro) sem precisar reabrir o programa, até escolher `0` para sair.

### Exemplo de sessão

```
=============================================
  Media DateTime Shift
  Corrige data/hora de fotos e vídeos
=============================================

O que deseja fazer?

  1 - Alterar DATA  (ajusta por dias, ex: +1, -3)
  2 - Alterar HORA  (ajusta por horas, ex: +3, -5)
  0 - Sair

Escolha uma opção: 2

=============================================
  Media DateTime Shift
  Alterar HORA
=============================================

Quantas horas (+1, -1)? +1

O que deseja processar?
  [1] Diretório inteiro (busca recursiva)
  [2] Arquivos específicos
Escolha [1/2]: 1
Caminho do diretório: /Volumes/Media_Dock/2026-06-Viagem

Encontrados 3 arquivo(s):
  - 2 JPG
  - 1 MOV

Executar em modo simulação (não altera nada)? [s/N]: n
Manter backups dos arquivos originais (recomendado)? [S/n]:

Resumo da operação:
  Ajuste: +1 horas (total: +1 horas)
  Arquivos: 3
  Modo: APLICAR ALTERAÇÕES
  Backups: sim

Confirma a operação? [s/N]: s
✓ IMG_0001.JPG  (2026-06-21 11:45:00 -> 2026-06-21 12:45:00)
✓ IMG_0002.JPG  (2026-06-21 11:47:12 -> 2026-06-21 12:47:12)
✓ VID_0001.MOV  (2026-06-21 11:50:00 -> 2026-06-21 12:50:00)
100%|████████████████████████████| 3/3 [00:01<00:00, 2.4arquivo/s]

Concluído: 3 sucesso(s), 0 erro(s).

Pressione ENTER para voltar ao menu...
```

Repare na linha de cada arquivo: ela mostra a hora **lida do próprio
arquivo antes do ajuste** e a hora **resultante**, então dá para
conferir na hora se o resultado bate com o esperado — sem precisar abrir
o Finder ou o Photos depois.

> **Atenção — o ajuste é cumulativo:** cada execução soma o
> deslocamento em cima do que já está gravado no arquivo. Se você rodar
> `+1` hora duas vezes no mesmo arquivo (por exemplo, testando de novo
> sem perceber que já tinha aplicado antes), o resultado final será
> `+2` horas em relação à data original — e não é um bug, é exatamente
> como um "shift" relativo deve funcionar. Se quiser desfazer um teste,
> restaure a partir do arquivo de backup (`arquivo.jpg_original`).
>
> O backup é sempre **atualizado a cada execução** (reflete o estado
> imediatamente anterior à última vez que você rodou o programa nesse
> arquivo — não um teste antigo de várias execuções atrás). Isso evita
> uma armadilha real que existia antes: o `exiftool`, por padrão, só
> cria esse backup na primeira vez que mexe num arquivo e não o
> atualiza depois — então, depois de testar o mesmo arquivo várias
> vezes, o backup ficava "para trás" e dava a falsa impressão de que o
> programa tinha somado mais horas do que o pedido. Agora isso não
> acontece mais: o backup sempre corresponde a "logo antes da última
> execução".

### Opção 3 — Definir data/hora exata (sem calcular a diferença manualmente)

Em vez de você descobrir e digitar "+4 horas" ou "-3 dias", essa opção
deixa você digitar diretamente a data/hora **certa** de um arquivo, e o
programa calcula o ajuste necessário sozinho.

Como funciona:

1. Você escolhe os arquivos (diretório ou específicos), igual às
   outras opções.
2. O programa usa o **primeiro arquivo da lista** como referência, lê a
   data/hora atual gravada nele e mostra na tela.
3. Você digita a data/hora **certa** desse arquivo de referência, em um
   destes dois formatos:
   - `DD/MM/AAAA HH:MM:SS` (ou sem segundos: `DD/MM/AAAA HH:MM`) — use
     quando a **data** também estiver errada, não só a hora.
   - Só `HH:MM:SS` (ou `HH:MM`) — mantém a mesma data do arquivo de
     referência, só troca o horário. É o caso mais comum (fuso horário
     errado, data certa).
4. O programa calcula a diferença e aplica **esse mesmo ajuste** a
   todos os arquivos selecionados — preservando a diferença de tempo
   entre eles. Ou seja, se você selecionou vários arquivos, eles **não**
   ficam todos com a mesma data/hora; cada um recebe o mesmo
   deslocamento, mantendo a ordem cronológica entre as fotos/vídeos.

#### Exemplo de sessão (opção 3)

```
=============================================
  Media DateTime Shift
  Definir data/hora exata
=============================================

O que deseja processar?
  [1] Diretório inteiro (busca recursiva)
  [2] Arquivos específicos
Escolha [1/2]: 2
Caminho completo (pode separar por vírgula): /Volumes/Photos128GB/DCIM/Camera01/VID_20260617_121821_394.mp4

Encontrados 1 arquivo(s):
  - 1 MP4

Arquivo de referência: /Volumes/Photos128GB/DCIM/Camera01/VID_20260617_121821_394.mp4
Data/hora atual desse arquivo: 17/06/2026 11:18:21

Qual é a data/hora CERTA desse arquivo?
  'DD/MM/AAAA HH:MM:SS' (data e hora), ou
  'HH:MM:SS' (só a hora, mantém a mesma data)
> 12:18:21

Ajuste calculado: +1h

Executar em modo simulação (não altera nada)? [s/N]: n
Manter backups dos arquivos originais (recomendado)? [S/n]:

Resumo da operação:
  Ajuste calculado: +1h
  Arquivos: 1
  Modo: APLICAR ALTERAÇÕES
  Backups: sim

Confirma a operação? [s/N]: s
✓ VID_20260617_121821_394.mp4  (2026-06-17 11:18:21 -> 2026-06-17 12:18:21)

Concluído: 1 sucesso(s), 0 erro(s).
```

> Se o arquivo de referência (o primeiro da seleção) não tiver nenhuma
> tag de data EXIF/QuickTime legível, o programa avisa e cancela —
> escolha um arquivo com metadados de data para usar como referência.

## Removendo os backups depois de conferir o resultado

O programa cria arquivos `*_original` como backup (sempre o mais
recente — ver aviso acima). Depois de confirmar que tudo ficou certo,
você pode removê-los manualmente:

```bash
find /Volumes/Media_Dock/2026-06-Viagem -name "*_original" -delete
```

## Como a data/hora do Finder é sincronizada

O programa lê a data **gravada na própria foto/vídeo** (EXIF
`DateTimeOriginal`, ou `CreateDate` como alternativa) antes de fazer
qualquer alteração, aplica o ajuste e usa **esse mesmo valor corrigido**
para atualizar a data do Finder (modificação e, se possível, criação).

Isso evita um problema comum: o `mtime` que o macOS mostra no Finder
pode não bater com a data real da foto se o arquivo foi copiado,
sincronizado com a nuvem ou recebido via AirDrop — nesses casos, a data
"de disco" reflete o momento da cópia, não a captura original. Agora o
ajuste sempre parte da data real do arquivo, então `11:45` com ajuste de
`+1` hora vira `12:45` tanto no EXIF quanto no Finder — nunca um valor
baseado em quando o arquivo foi copiado para a pasta.

Se um arquivo não tiver nenhuma tag de data legível (raro, mas pode
acontecer com metadados corrompidos ou removidos), o programa avisa ao
final e usa o `mtime` que já estava em disco como melhor alternativa
disponível.

## Limitações conhecidas

- A data de **criação** (Finder) só é ajustada se o `SetFile` (Xcode
  Command Line Tools) estiver instalado. Sem ele, apenas a data de
  modificação é alterada.
- Tags de **GPS** não são deslocadas — elas normalmente já são gravadas em
  UTC pela câmera, então um erro de fuso horário local não costuma afetá-las.
- O script assume que **todos** os arquivos selecionados precisam do
  **mesmo** deslocamento. Para lotes com fusos diferentes, rode o programa
  uma vez para cada grupo de arquivos.
- Arquivos sem nenhuma tag de data EXIF/QuickTime legível usam o `mtime`
  que já estava em disco como referência (em vez da data real, que não
  existe nesse caso) — o programa avisa quais arquivos caíram nesse caso.
- **Cartões SD / mídia removível via leitor USB**: arquivos grandes
  (vídeos) podem demorar bastante para processar (a velocidade de
  escrita de um cartão SD é bem menor que a de um SSD interno). O
  programa já lida com isso corretamente (força a escrita a ser
  confirmada no disco antes de ajustar a data, evitando que o
  ajuste seja sobrescrito), mas processos do macOS — como o app
  **Fotos** ou o **Image Capture**, que costumam escanear cartões com
  pasta `DCIM` automaticamente — podem competir pelo acesso ao cartão
  e deixar tudo mais lento ainda. Vale desativar a importação
  automática do Fotos antes de processar um cartão diretamente.

## Documentação técnica

Veja [`docs/TECHNICAL.md`](docs/TECHNICAL.md) para detalhes de
arquitetura, das tags de metadados usadas e do tratamento de erros.

## Licença

MIT — veja [`LICENSE`](LICENSE).
