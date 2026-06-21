# Documentação Técnica — Media DateTime Shift

## Visão geral da arquitetura

```
media-datetime-shift/
├── install.sh                          # provisionamento (venv + exiftool)
├── requirements.txt                    # deps de runtime (tqdm)
├── requirements-dev.txt                # deps de teste (pytest)
├── src/
│   └── media_datetime_shift.py         # único módulo: CLI interativa
├── tests/
│   └── test_media_datetime_shift.py    # testes das funções puras
├── docs/
│   └── TECHNICAL.md                    # este arquivo
└── README.md
```

O programa é deliberadamente um único arquivo Python, dividido em três
camadas:

1. **Funções puras** (`parse_signed_int_offset`, `build_exiftool_shift_expr`,
   `parse_exiftool_datetime`, `format_shift_line`,
   `discover_files_in_directory`, `resolve_specific_files`,
   `summarize_extensions`) — sem efeitos colaterais, fáceis de testar
   isoladamente com `pytest`.
2. **Funções de I/O / efeito colateral** (`read_primary_datetime`,
   `shift_exif_metadata`, `sync_filesystem_dates_to`,
   `shift_filesystem_dates_relative`) — dependem de processos externos
   (`exiftool`, `SetFile`) e do sistema de arquivos.
3. **Camada de menu/interação** (`run`, `run_shift_flow`,
   `ask_offset`, `ask_target_files`, `process_files`) — o loop principal
   apresenta um menu (`1` Alterar DATA, `2` Alterar HORA, `0` Sair) e
   delega para `run_shift_flow`, que reaproveita a mesma engine de shift
   tanto para dias quanto para horas.

Essa separação permite testar toda a lógica de parsing e descoberta de
arquivos sem precisar de um Mac real ou do `exiftool` instalado (por isso
os testes rodam normalmente em CI Linux). As funções de I/O são testadas
com `unittest.mock.patch`, simulando o retorno do `exiftool` sem precisar
do binário real.

### Menu: "Alterar DATA" vs. "Alterar HORA"

Internamente, o motor de shift sempre trabalha em **horas totais** — é a
unidade nativa tanto do `exiftool` quanto de `datetime.timedelta`. O
dicionário `MENU_OPTIONS` define, para cada opção de menu, um
multiplicador que converte a entrada do usuário para essa unidade comum:

```python
MENU_OPTIONS = {
    "1": {"titulo": "Alterar DATA", "unidade": "dias",  "multiplicador": 24},
    "2": {"titulo": "Alterar HORA", "unidade": "horas", "multiplicador": 1},
}
```

Ou seja, `1 - Alterar DATA` com entrada `+2` vira `2 * 24 = 48` horas
internamente; `2 - Alterar HORA` com entrada `-5` permanece `-5` horas.
Isso evita duplicar a lógica de shift — a única diferença entre as duas
opções de menu é a unidade que o usuário enxerga e o multiplicador
aplicado antes de chamar a mesma engine.

## Por que `exiftool` e não uma lib Python pura?

Bibliotecas Python "puras" para EXIF (Pillow, piexif) cobrem bem JPEG, mas
**não** suportam HEIC, DNG, a maioria dos formatos RAW, nem os contêineres
de vídeo (MOV/MP4 com tags QuickTime). O `exiftool` (Phil Harvey) é o
padrão de fato para metadados de mídia, suporta centenas de formatos, e
tem **suporte nativo a deslocamento de datas** via operador `+=`/`-=` na
tag virtual `AllDates`, o que evita reimplementar parsing/escrita de EXIF
manualmente.

O programa chama o binário `exiftool` via `subprocess`, em vez de usar o
wrapper Python `PyExifTool`, para manter as dependências mínimas e evitar
o overhead de manter um processo `exiftool` "stay-open" — cada chamada é
independente e fácil de depurar isoladamente (o comando exato pode ser
reproduzido manualmente no terminal).

### Sintaxe do deslocamento

O `exiftool` espera o deslocamento no formato:

```
[+-]=Y:M:D H:M:S
```

O programa sempre fixa a parte `Y:M:D` em `0:0:0` e usa apenas a parte
`H:M:S`, por exemplo, para `+27` horas:

```
-AllDates+=0:0:0 27:0:0
```

O `exiftool` resolve internamente o "carry" de horas para dias (e, se
necessário, meses/anos) ao recalcular a data — por isso um valor como
`+27` corrige tanto a **hora** quanto a **data**, sem precisar de um
campo separado para dias.

### Tags afetadas

- **`AllDates`**: tag de conveniência do exiftool que mapeia para
  `DateTimeOriginal`, `CreateDate` e `ModifyDate` (cobre EXIF de
  JPEG/HEIC/DNG/RAW e os tags equivalentes de TIFF/PNG).
- **Tags QuickTime explícitas**, adicionadas apenas para arquivos de
  vídeo (`.mov`, `.mp4`, `.m4v`, `.avi`, `.3gp`, `.mts`, `.m2ts`), pois
  `AllDates` não garante cobertura dos metadados de contêiner/trilha:
  - `QuickTime:CreateDate`, `QuickTime:ModifyDate`
  - `QuickTime:TrackCreateDate`, `QuickTime:TrackModifyDate`
  - `QuickTime:MediaCreateDate`, `QuickTime:MediaModifyDate`

Tags de **GPS** (`GPSDateTime`, `GPSTimeStamp`) não são tocadas
deliberadamente — já costumam ser gravadas em UTC pelo hardware GPS,
independente do fuso configurado no aparelho.

A flag `-m` é usada para ignorar avisos "minor" do exiftool (comuns em
certos arquivos RAW/HEIC com metadados não-padrão), sem impedir a
gravação dos tags válidos.

## Datas do sistema de arquivos (macOS)

### O bug original e por que ele acontecia

Numa primeira versão, o deslocamento do sistema de arquivos era
calculado **a partir do `mtime` que já estava em disco**
(`stat.st_mtime` + delta), em vez de a partir da data real gravada no
EXIF. Isso parecia razoável em teoria, mas quebra na prática: o `mtime`
de um arquivo reflete a última vez que ele foi *escrito no disco onde
está agora* — não a data em que a foto/vídeo foi originalmente
capturado. Copiar o arquivo (AirDrop, sincronizar com a nuvem, mover
entre pastas/discos) costuma atualizar o `mtime` para o momento da
cópia, deixando-o **dessincronizado** do EXIF.

Resultado observado: ajustar `+1` hora num arquivo cujo EXIF dizia
`11:45` produzia um Finder mostrando `12:20` em vez de `12:45` — porque
o `+1h` foi somado ao `mtime` (que já estava errado), não à hora real
gravada na foto.

### A correção: o EXIF é a única fonte da verdade

Agora o fluxo (em `process_files`) é:

```python
original_dt = read_primary_datetime(file_path)   # lê ANTES de alterar
ok, msg = shift_exif_metadata(file_path, total_hours, keep_backup)
if ok and original_dt is not None:
    sync_filesystem_dates_to(file_path, original_dt + delta, has_setfile)
```

1. **`read_primary_datetime`** lê a tag `DateTimeOriginal` (fallback:
   `CreateDate`) do arquivo **antes** de qualquer alteração — essa é a
   data real da foto/vídeo, independente do que o `mtime` em disco diz.
2. **`shift_exif_metadata`** desloca o EXIF normalmente (como antes).
3. **`sync_filesystem_dates_to`** define `mtime`/`atime`/`birthtime`
   para `original_dt + delta` — ou seja, **o mesmo valor exato** que
   acabou de ser gravado no EXIF, eliminando qualquer divergência.

```python
def sync_filesystem_dates_to(file_path, target_dt, has_setfile):
    ts = target_dt.timestamp()
    os.utime(file_path, (ts, ts))
    if has_setfile:
        formatted = target_dt.strftime("%m/%d/%Y %H:%M:%S")
        subprocess.run(["SetFile", "-d", formatted, file_path], ...)
```

### Fallback: arquivos sem data EXIF legível

Se `read_primary_datetime` não encontrar nenhuma tag de data válida
(arquivo sem metadados, ou com data zerada tipo `0000:00:00 00:00:00`),
não há referência confiável para sincronizar. Nesse caso o programa cai
de volta no comportamento antigo — `shift_filesystem_dates_relative`,
que desloca relativamente ao `mtime`/`atime`/`birthtime` que já estavam
em disco — e o arquivo é listado no aviso final ("sem data EXIF/QuickTime
legível") para o usuário saber que esse caso específico pode não ser
exato.

### Birthtime (data de criação)

O `os.utime()` do Python só permite alterar **mtime** (modificação) e
**atime** (acesso) — não existe API multiplataforma para alterar a
**birthtime** (data de criação / "Date Added" no Finder). Para isso o
programa usa o utilitário `SetFile -d`, das **Xcode Command Line
Tools**. Se não estiver instalado, o programa detecta isso no início
(`shutil.which("SetFile")`) e segue normalmente, apenas avisando que a
data de criação não será alterada.

## Natureza cumulativa do shift (importante para depuração)

O `exiftool` (e, por extensão, este programa) faz um deslocamento
**relativo**, não define um valor absoluto. Isso significa que rodar o
programa duas vezes no mesmo arquivo com `+1` hora produz `+2` horas em
relação ao valor original — cada execução soma em cima do que já está
gravado, não em cima de um "original" lembrado externamente.

Isso foi confirmado empiricamente (instalando `exiftool`/`ffmpeg` num
ambiente de teste e rodando `process_files` duas vezes seguidas no
mesmo arquivo): a primeira chamada levou `11:45 → 12:45` corretamente;
chamando de novo no mesmo arquivo, sem restaurar o backup, levou
`12:45 → 13:45` — um total de `+2h` em relação ao `11:45` original, que
é o comportamento correto e esperado de um shift relativo, mas pode
parecer um bug se o usuário não perceber que já tinha rodado antes (por
exemplo, testando a mesma pasta em duas versões diferentes do script,
ou voltando ao menu e repetindo a operação sem querer).

Para tornar isso visível e evitar essa confusão, cada arquivo agora
imprime o **antes e depois** durante o processamento (e também no modo
simulação, já que `read_primary_datetime` é chamada antes de decidir se
vai escrever):

```python
def format_shift_line(file_path, original_dt, new_dt) -> str:
    if original_dt is None:
        return f"{file_path}  (sem data EXIF; sistema de arquivos deslocado pelo mtime anterior)"
    fmt = "%Y-%m-%d %H:%M:%S"
    return f"{file_path}  ({original_dt.strftime(fmt)} -> {new_dt.strftime(fmt)})"
```

```
✓ IMG_0001.JPG  (2026-06-21 11:45:00 -> 2026-06-21 12:45:00)
```

`log_line()` usa `tqdm.write()` (em vez de `print()`) quando a barra de
progresso está ativa, para a linha não quebrar o desenho da barra no
terminal.

Se o resultado mostrado parecer "dobrado" em relação ao esperado, a
causa mais provável é justamente essa: o arquivo já tinha sido alterado
numa execução anterior. Para zerar e testar de novo, restaure o backup
(`arquivo.jpg_original`, criado automaticamente quando "Manter backups"
está ativado) antes de rodar de novo.

## Tratamento de erros e segurança

- **Backups**: por padrão, o `exiftool` mantém uma cópia do arquivo
  original (`arquivo.jpg_original`) antes de qualquer escrita. Isso só é
  desativado se o usuário explicitamente responder "não" à pergunta de
  backup (usa `-overwrite_original`).
- **Modo simulação (dry-run)**: lista os arquivos que seriam processados
  sem chamar `exiftool` nem tocar no sistema de arquivos.
- **Confirmação explícita**: nenhuma alteração é aplicada sem uma
  confirmação final do usuário, depois de ver o resumo (quantidade de
  arquivos, deslocamento, modo).
- **Arquivos não suportados são ignorados silenciosamente na busca por
  diretório**, e geram um aviso explícito quando informados diretamente
  como caminho específico.
- Erros do `exiftool` por arquivo não interrompem o lote inteiro — são
  coletados e exibidos ao final, com a contagem de sucesso/erro.

## Limitações conhecidas e possíveis evoluções futuras

| Limitação | Possível evolução |
|---|---|
| Sistema de arquivos só suportado no macOS (`st_birthtime`) | Adicionar branch para Linux/Windows (sem birthtime nativo) |
| Mesmo deslocamento para todo o lote | Permitir múltiplos grupos/deslocamentos em uma sessão |
| Sem suporte a fuso horário explícito (ex: "de UTC-3 para UTC+1") | Adicionar modo alternativo que pergunta fuso de origem/destino e calcula o delta |
| GPS não ajustado | Tag opcional `-GPSDateTime` caso o usuário confirme que também precisa ajustar |

## Testes

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v
```

Os testes cobrem apenas as funções puras (parsing de deslocamento com
sinal, conversão dia→hora/hora→hora via `MENU_OPTIONS`, montagem da
expressão de shift do exiftool, resolução de arquivos por glob,
sumarização por extensão) — não testam a integração real com `exiftool`
ou `SetFile`, que dependem do ambiente macOS. Para validar a integração
real, use o **modo simulação** do próprio programa em um diretório de
teste antes de aplicar em arquivos importantes.
