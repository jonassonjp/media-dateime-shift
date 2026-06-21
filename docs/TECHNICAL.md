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
   `format_timedelta`, `parse_exiftool_datetime`, `parse_target_datetime`,
   `format_shift_line`, `discover_files_in_directory`,
   `resolve_specific_files`, `summarize_extensions`) — sem efeitos
   colaterais, fáceis de testar isoladamente com `pytest`.
2. **Funções de I/O / efeito colateral** (`read_primary_datetime`,
   `backup_file_path`, `shift_exif_metadata`, `flush_pending_writes`,
   `sync_filesystem_dates_to`, `shift_filesystem_dates_relative`) —
   dependem de processos externos (`exiftool`, `SetFile`) e do sistema
   de arquivos.
3. **Camada de menu/interação** (`run`, `run_shift_flow`,
   `run_set_exact_datetime_flow`, `ask_offset`, `ask_target_datetime`,
   `ask_target_files`, `process_files`) — o loop principal apresenta um
   menu (`1` Alterar DATA, `2` Alterar HORA, `3` Definir data/hora
   exata, `0` Sair) e delega para o fluxo correspondente, todos
   reaproveitando a mesma engine de shift.

Essa separação permite testar toda a lógica de parsing e descoberta de
arquivos sem precisar de um Mac real ou do `exiftool` instalado (por isso
os testes rodam normalmente em CI Linux). As funções de I/O são testadas
com `unittest.mock.patch`, simulando o retorno do `exiftool` sem precisar
do binário real.

### A engine interna trabalha em `timedelta`, não em "horas inteiras"

Inicialmente o motor de shift só aceitava um número inteiro de horas.
Isso mudou quando a opção 3 ("Definir data/hora exata") foi adicionada:
o deslocamento ali é calculado como `data_certa - data_atual_do_arquivo`,
que raramente cai num número redondo de horas (ex: `4:28:29`). Por isso
toda a engine — `shift_exif_metadata`, `sync_filesystem_dates_to`,
`shift_filesystem_dates_relative`, `process_files` — foi generalizada
para trabalhar com `datetime.timedelta` (dias/horas/minutos/segundos)
do início ao fim, em vez de um `int` de horas.

`build_exiftool_shift_expr(delta)` converte esse timedelta para o
formato que o exiftool espera:

```python
def build_exiftool_shift_expr(delta: timedelta) -> str:
    sign = "+" if delta.total_seconds() >= 0 else "-"
    total_seconds = abs(int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{sign}=0:0:{days} {hours}:{minutes}:{seconds}"
```

E `format_timedelta(delta)` formata o mesmo valor de forma legível para
o usuário (ex: `+4h 28min 29s`, `+1d 3h`), omitindo componentes zerados.

### Opções 1/2 ("Alterar DATA"/"Alterar HORA"): deslocamento relativo

`MENU_OPTIONS` define, para cada uma dessas duas opções, um
multiplicador que converte a entrada do usuário num `timedelta`:

```python
MENU_OPTIONS = {
    "1": {"titulo": "Alterar DATA", "unidade": "dias",  "multiplicador": 24},
    "2": {"titulo": "Alterar HORA", "unidade": "horas", "multiplicador": 1},
}
```

`ask_offset()` retorna `(valor_digitado, timedelta(hours=valor*multiplicador))`.
Ou seja, `1 - Alterar DATA` com entrada `+2` vira `timedelta(days=2)`;
`2 - Alterar HORA` com entrada `-5` vira `timedelta(hours=-5)`. Essas
duas opções nunca produzem minutos/segundos — só existem para dar uma
unidade mais natural (dias vs. horas) à mesma operação de deslocamento
relativo.

### Opção 3 ("Definir data/hora exata"): deslocamento calculado, com precisão de segundos

Pensada para o caso em que o usuário **já sabe** a data/hora certa de um
arquivo (ex: comparando com outra foto/vídeo de referência) e não quer
fazer a conta de cabeça. Implementada em `run_set_exact_datetime_flow`:

1. Pede os arquivos (mesmo fluxo de `ask_target_files`).
2. Usa o **primeiro arquivo da lista ordenada** como referência, lê sua
   data atual via `read_primary_datetime` (se não houver data legível,
   cancela com uma mensagem clara — não há como calcular sem isso).
3. Pede a data/hora certa via `ask_target_datetime`, que usa
   `parse_target_datetime` para interpretar:
   - `DD/MM/AAAA HH:MM:SS` (ou sem segundos) — data E hora completas;
   - só `HH:MM:SS` (ou `HH:MM`) — mantém a **data** do arquivo de
     referência, troca só a hora (`datetime.combine(reference.date(), time)`).
4. Calcula `delta = data_certa - data_atual_da_referência` (um
   `timedelta` com precisão de segundos).
5. Aplica esse **mesmo delta** a TODOS os arquivos selecionados via
   `process_files(files, delta, ...)` — preservando a diferença de
   tempo relativa entre eles. Importante: a opção 3 **não define a
   mesma data/hora para todo mundo**; ela calcula um deslocamento a
   partir de um arquivo e aplica esse deslocamento aos demais, exatamente
   como as opções 1/2 fazem — só que o valor do deslocamento é
   *calculado* em vez de digitado diretamente.

Esse comportamento foi validado com um teste de integração real
(exiftool/ffmpeg instalados num ambiente de teste, dois vídeos com
horários diferentes): ao informar a hora certa do primeiro vídeo
(referência), o segundo vídeo recebeu o mesmo deslocamento, preservando
exatamente a diferença de tempo original entre os dois (7min29s).

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

O programa sempre fixa a parte `Y:M` (ano/mês) em `0:0` e deriva `D
H:M:S` diretamente do `timedelta` calculado, via `build_exiftool_shift_expr`.
Por exemplo, para `timedelta(hours=27)` (que o Python já normaliza
internamente para 1 dia + 3 horas):

```
-AllDates+=0:0:1 3:0:0
```

E para um deslocamento com precisão de segundos, como os calculados
pela opção 3 ("Definir data/hora exata"), por exemplo
`timedelta(hours=4, minutes=28, seconds=29)`:

```
-AllDates+=0:0:0 4:28:29
```

O `exiftool` resolve internamente qualquer "carry" adicional (de horas
para dias, ou de dias para meses/anos) ao recalcular a data — por isso
um deslocamento grande corrige tanto a **hora** quanto a **data**, sem
precisar de lógica extra da nossa parte.

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

### Condição de corrida em mídia removível lenta (cartão SD / leitor USB)

Bug real, reproduzido e confirmado com um usuário processando vídeos
direto de um cartão SD (`/Volumes/<cartão>/DCIM/...`): depois de uma
execução aparentemente bem-sucedida (EXIF corrigido corretamente, sem
erros no log), o `mtime` do arquivo ficava com a data/hora do momento
em que o script rodou ("agora"), e não com o valor corrigido que o
programa deveria ter aplicado.

**Diagnóstico**: um teste isolado, chamando só `os.utime()` manualmente
no mesmo arquivo, funcionou perfeitamente — então não era uma
limitação do driver exFAT em si. O detalhe que resolveu o mistério foi
o tempo de execução do log: **33 segundos para um único arquivo de
~1GB** (vídeo). Isso indica I/O bem mais lento que um SSD interno
(típico de cartão SD via leitor USB).

**Causa**: condição de corrida entre duas escritas no mesmo arquivo:

1. `exiftool` reescreve o conteúdo do arquivo (potencialmente ~1GB) —
   em mídia lenta, essa escrita pode ficar em buffer no sistema
   operacional por um tempo antes de ser fisicamente confirmada no
   cartão.
2. Logo em seguida, `sync_filesystem_dates_to()` chama `os.utime()`
   para corrigir a data — isso atualiza o metadado imediatamente, no
   cache do SO.
3. Quando a escrita grande do passo 1 finalmente é fisicamente
   confirmada no cartão (podendo ser segundos depois), o driver do
   sistema de arquivos atualiza o `mtime` de novo, **sobrescrevendo
   silenciosamente** o valor que tínhamos acabado de corrigir no
   passo 2 — com o horário em que essa escrita física terminou
   ("agora").

**Correção**: forçar a escrita do `exiftool` a ser fisicamente
confirmada (fsync) ANTES de tocarmos nos metadados de data, garantindo
que nosso `os.utime()` seja sempre a última coisa a acontecer:

```python
def flush_pending_writes(file_path):
    try:
        fd = os.open(file_path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass  # mídia/SO sem suporte; seguimos mesmo assim

def sync_filesystem_dates_to(file_path, target_dt, has_setfile):
    flush_pending_writes(file_path)
    ts = target_dt.timestamp()
    os.utime(file_path, (ts, ts))
    ...
```

`fsync(fd)` flushea as páginas sujas associadas ao **inode** do
arquivo (não importa se o fd foi aberto para leitura ou escrita), então
abrir o arquivo em modo `O_RDONLY` só para forçar o flush é suficiente
e não corre risco de alterar o conteúdo. A mesma chamada foi adicionada
em `shift_filesystem_dates_relative()` (o fallback para arquivos sem
data EXIF), pelo mesmo motivo.

Esse tipo de condição de corrida é mais comum em mídia removível
(cartões SD, pen drives) do que em discos internos SSD/APFS, onde a
latência de escrita é baixa o suficiente para o problema praticamente
nunca aparecer — por isso não tinha sido percebido nos testes
anteriores, todos feitos em arquivos já no disco principal.

## Natureza cumulativa do shift (importante para depuração)

O `exiftool` (e, por extensão, este programa) faz um deslocamento
**relativo**, não define um valor absoluto. Isso significa que rodar o
programa duas vezes no mesmo arquivo com `+1` hora produz `+2` horas em
relação ao valor original — cada execução soma em cima do que já está
gravado, não em cima de um "original" lembrado externamente. Isso é
esperado e correto — mas dois pontos relacionados causavam confusão real
ao depurar isso, e o segundo era um bug de verdade:

### 1. O log agora mostra o antes/depois de cada arquivo

Para tornar o efeito cumulativo visível, cada arquivo imprime o
**antes e depois** durante o processamento (também no modo simulação,
já que `read_primary_datetime` é chamada antes de decidir se vai
escrever):

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

### 2. Bug real: o backup do `exiftool` não acompanhava execuções seguintes

Inicialmente o backup era feito pelo próprio `exiftool` (comportamento
padrão: renomear o arquivo para `*_original` antes de escrever). O
problema, confirmado empiricamente: **o `exiftool` só cria esse backup
na primeira vez** que mexe num arquivo. Em execuções seguintes — mesmo
com "Manter backups" ativado de novo — ele **não atualiza** o backup
existente; ele fica congelado no estado da primeiríssima execução,
enquanto o arquivo principal segue acumulando ajustes a cada chamada.

```
Execução 1 (+1h): arquivo 11:45→12:45 | backup grava 11:45 (ok)
Execução 2 (+1h): arquivo 12:45→13:45 | backup CONTINUA mostrando 11:45 (!)
```

Isso fazia o backup parecer "a referência de antes do último teste",
quando na verdade era "a referência de antes do primeiro teste, há
várias execuções atrás" — levando a achar que o programa tinha somado
mais horas do que o pedido, quando na realidade cada execução individual
estava correta; só o backup é que estava desatualizado.

**Correção**: o backup agora é feito por NÓS (`shutil.copy2`), sempre
sobrescrevendo o anterior, ANTES de cada chamada ao `exiftool` — que
passa a rodar sempre com `-overwrite_original` (não dependemos mais do
mecanismo de backup dele):

```python
def shift_exif_metadata(file_path, hours, keep_backup):
    if keep_backup:
        shutil.copy2(file_path, backup_file_path(file_path))  # sempre sobrescreve

    cmd = ["exiftool", "-m", f"-AllDates{shift_expr}", "-overwrite_original"]
    ...
```

Com isso, `arquivo.ext_original` sempre reflete o estado **imediatamente
anterior à última execução** — nunca mais um teste antigo esquecido.
Validado com um teste de integração real (instalando `exiftool`/`ffmpeg`
e rodando duas execuções seguidas: `+3h` e depois `+1h`) — depois da
segunda execução, o backup mostrou corretamente o valor de ANTES da
segunda execução (`14:45:26`, resultado da primeira), não mais o valor
original de várias execuções atrás (`11:45:26`).

Se mesmo assim o resultado parecer "dobrado" em relação ao esperado, a
causa mais provável continua sendo a mesma raiz (efeito cumulativo): o
arquivo já tinha sido alterado numa execução anterior a esta correção,
ou numa sessão de teste anterior. Para zerar e testar do zero, restaure
o backup mais recente antes de rodar de novo.

## Tratamento de erros e segurança

- **Backups**: quando "Manter backups" está ativado, o programa copia o
  arquivo (`shutil.copy2`) para `arquivo.ext_original` **antes** de
  qualquer escrita, sempre sobrescrevendo um backup anterior — nunca
  dependemos do backup automático do `exiftool` (ver seção acima sobre
  por que isso importa). Se a cópia falhar (ex: disco cheio,
  permissão), o arquivo NÃO é alterado.
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
